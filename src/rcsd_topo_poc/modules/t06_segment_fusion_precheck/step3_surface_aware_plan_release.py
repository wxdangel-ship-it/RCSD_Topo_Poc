from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .io import default_run_id, read_features, suppress_feature_json_outputs, write_json
from .parsing import parse_id_list, unique_preserve_order
from .schemas import (
    STEP2_REPLACEMENT_PLAN_STEM,
    STEP3_DIR,
    STEP3_SWSD_FRCSD_SEGMENT_RELATION_STEM,
)
from .step3_semantic_junction_groups import (
    discover_intersection_match_path,
    refresh_semantic_junction_topology_audit,
    valid_t05_relation_targets,
)
from .step3_output_slimming import retire_intermediate_step3_plan
from .step3_segment_replacement import T06Step3Artifacts, run_t06_step3_segment_replacement
from .step3_topology_connectivity_audit import STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM
from .step3_surface_topology_audit import run_surface_topology_postprocess


RETAINED_JUNCTION_GATE_REASON = "junction_alignment_to_retained_swsd_exceeds_topology_gate"
SURFACE_RELEASE_RISK = "junction_alignment_surface_audit_release"
SURFACE_RELEASE_ROLLBACK_REASON = "junction_alignment_surface_release_failed_topology_gate"
SURFACE_RELEASE_PLAN_STEM = "t06_step3_surface_aware_replacement_plan"
SURFACE_RELEASE_AUDIT = "t06_step3_surface_aware_plan_release_audit.json"
VISUAL_CONFLICT_REASON = "visual_consistency_road_conflict_with_primary_replacement_plan"
VISUAL_CONFLICT_RELEASE_RISK = "visual_conflict_controlled_release"
VISUAL_CONFLICT_ROLLBACK_REASON = "visual_conflict_release_failed_topology_gate"
RETAINED_JUNCTION_ATTACHMENT_GAP_M = 20.0
OPTIONAL_JUNCTION_ANCHOR_RELEASE_MAX_GAP_M = 50.0
OPTIONAL_JUNCTION_ANCHOR_RELEASE_REASON = "auto_closed_step2_optional_junc_anchor"
T05_SEMANTIC_JUNCTION_RELEASE_REASON = "auto_closed_t05_semantic_junction_relation"
SURFACE_RELEASE_REASONS = {
    "auto_closed",
    "auto_closed_surface_1v1",
    "auto_closed_t04_patch_1v1",
    "auto_closed_step2_junc_1v1",
    "auto_closed_relation_mapped_boundary_1v1",
    "auto_closed_selected_replacement_endpoint",
    OPTIONAL_JUNCTION_ANCHOR_RELEASE_REASON,
    T05_SEMANTIC_JUNCTION_RELEASE_REASON,
}


def run_surface_aware_step3_segment_replacement(
    *,
    step2_replaceable_path: str | Path,
    step2_special_junction_group_audit_path: str | Path | None,
    step2_group_replacement_audit_path: str | Path | None,
    swsd_segment_path: str | Path,
    swsd_roads_path: str | Path,
    swsd_nodes_path: str | Path,
    rcsdroad_path: str | Path,
    rcsdnode_path: str | Path,
    out_root: str | Path,
    run_id: str | None,
    surface_inputs: dict[str, Path | None],
    surface_topology_closure: bool,
    progress: bool,
) -> tuple[T06Step3Artifacts, dict[str, Any] | None]:
    has_surface_inputs = any(surface_inputs.values())
    topology_coverage_cache: dict[Any, Any] = {}
    preflight_plan_rows = _preflight_replacement_plan_rows(step2_replaceable_path)
    if has_surface_inputs and preflight_plan_rows:
        preplanned_result = _run_preplanned_release_step3(
            plan_rows=preflight_plan_rows,
            step2_replaceable_path=step2_replaceable_path,
            step2_special_junction_group_audit_path=step2_special_junction_group_audit_path,
            step2_group_replacement_audit_path=step2_group_replacement_audit_path,
            swsd_segment_path=swsd_segment_path,
            swsd_roads_path=swsd_roads_path,
            swsd_nodes_path=swsd_nodes_path,
            rcsdroad_path=rcsdroad_path,
            rcsdnode_path=rcsdnode_path,
            out_root=out_root,
            run_id=run_id,
            surface_inputs=surface_inputs,
            surface_topology_closure=surface_topology_closure,
            progress=progress,
            topology_coverage_cache=topology_coverage_cache,
        )
        if preplanned_result is not None:
            return preplanned_result
    initial_step3_kwargs = {
        "step2_replaceable_path": step2_replaceable_path,
        "step2_special_junction_group_audit_path": step2_special_junction_group_audit_path,
        "step2_group_replacement_audit_path": step2_group_replacement_audit_path,
        "step2_replacement_plan_path": None,
        "swsd_segment_path": swsd_segment_path,
        "swsd_roads_path": swsd_roads_path,
        "swsd_nodes_path": swsd_nodes_path,
        "rcsdroad_path": rcsdroad_path,
        "rcsdnode_path": rcsdnode_path,
        "out_root": out_root,
        "run_id": run_id,
        "junction_surface_path": surface_inputs.get("t05_surface_path"),
        "progress": progress,
    }
    artifacts = _run_step3(
        **initial_step3_kwargs,
        write_feature_json_outputs=not has_surface_inputs,
    )
    surface_summary = _run_surface(
        artifacts,
        swsd_segment_path=swsd_segment_path,
        swsd_roads_path=swsd_roads_path,
        surface_inputs=surface_inputs,
        surface_topology_closure=surface_topology_closure,
        write_feature_json_outputs=not has_surface_inputs,
        topology_coverage_cache=topology_coverage_cache,
    )
    if not has_surface_inputs:
        return artifacts, surface_summary

    original_plan_path = _summary_input_path(artifacts.summary_path, "step2_replacement_plan_path")
    if original_plan_path is None or not original_plan_path.is_file():
        audit = {
            "status": "skipped",
            "reason": "missing_replacement_plan",
            "full_step3_run_count": 1,
            "extra_step3_run_count": 0,
            "full_output_step3_run_count": 1,
            "validation_step3_run_count": 0,
        }
        _write_release_audit(artifacts.step_root, audit)
        _merge_release_summary(artifacts.summary_path, audit)
        return artifacts, surface_summary

    full_step3_run_count = 1
    baseline_fail_keys = _topology_fail_keys(artifacts.step_root)
    external_baseline_root = _external_baseline_step3_root(step2_replaceable_path, artifacts.step_root)
    external_baseline_fail_keys = _topology_fail_keys(external_baseline_root) if external_baseline_root else set()
    plan_rows = read_features(original_plan_path)
    incident_segments_by_node = _incident_segments_by_node(read_features(swsd_segment_path))
    release_rows, released = _surface_release_plan_rows(
        plan_rows,
        step_root=artifacts.step_root,
        swsd_segment_path=swsd_segment_path,
        swsd_nodes_path=swsd_nodes_path,
        rcsdnode_path=rcsdnode_path,
        incident_segments_by_node=incident_segments_by_node,
    )
    candidate_rows, visual_released = _visual_conflict_release_plan_rows(_copy_plan_rows(release_rows))
    candidate_plan: Path | None = None
    topology_safe_plan: Path | None = None
    rollback_plan_ids: set[str] = set()
    external_rollback_plan_ids: set[str] = set()
    visual_rollback_plan_ids: set[str] = set()
    visual_non_replaced_plan_ids: set[str] = set()
    visual_added_fail_keys: set[tuple[str, str, str, str, str]] = set()

    rollback_reference_fail_keys = external_baseline_fail_keys if external_baseline_root else baseline_fail_keys
    if released or visual_released:
        candidate_plan = _write_plan_json(artifacts.step_root, candidate_rows, "candidate")
        artifacts = _run_step3(
            step2_replaceable_path=step2_replaceable_path,
            step2_special_junction_group_audit_path=step2_special_junction_group_audit_path,
            step2_group_replacement_audit_path=step2_group_replacement_audit_path,
            step2_replacement_plan_path=candidate_plan,
            swsd_segment_path=swsd_segment_path,
            swsd_roads_path=swsd_roads_path,
            swsd_nodes_path=swsd_nodes_path,
            rcsdroad_path=rcsdroad_path,
            rcsdnode_path=rcsdnode_path,
            out_root=out_root,
            run_id=run_id,
            junction_surface_path=surface_inputs.get("t05_surface_path"),
            progress=progress,
            write_feature_json_outputs=False,
        )
        full_step3_run_count += 1
        surface_summary = _run_surface(
            artifacts,
            swsd_segment_path=swsd_segment_path,
            swsd_roads_path=swsd_roads_path,
            surface_inputs=surface_inputs,
            surface_topology_closure=surface_topology_closure,
            write_feature_json_outputs=False,
            topology_coverage_cache=topology_coverage_cache,
        )
        final_fail_keys = _topology_fail_keys(artifacts.step_root)
        added_fail_keys = final_fail_keys - rollback_reference_fail_keys
        if released:
            rollback_plan_ids = _rollback_plan_ids(
                added_fail_keys,
                released,
                candidate_rows,
                swsd_segment_path,
                incident_segments_by_node=incident_segments_by_node,
            )
        external_added_fail_keys = final_fail_keys - external_baseline_fail_keys if external_baseline_root else set()
        if released:
            external_rollback_plan_ids = (
                _rollback_plan_ids(
                    external_added_fail_keys,
                    released,
                    candidate_rows,
                    swsd_segment_path,
                    incident_segments_by_node=incident_segments_by_node,
                )
                - rollback_plan_ids
            )
        if visual_released:
            surface_safe_fail_keys = _fail_keys_after_release_rollback(
                final_fail_keys,
                released,
                rollback_plan_ids | external_rollback_plan_ids,
                incident_segments_by_node,
            )
            visual_added_fail_keys = surface_safe_fail_keys - rollback_reference_fail_keys
            visual_non_replaced_plan_ids = _visual_conflict_non_replaced_plan_ids(artifacts.step_root, visual_released)
            visual_rollback_plan_ids = _visual_conflict_rollback_plan_ids(
                visual_added_fail_keys,
                visual_released,
                swsd_segment_path,
                incident_segments_by_node=incident_segments_by_node,
            )
            visual_rollback_plan_ids = _filter_visual_topology_rollback_plan_ids(
                visual_rollback_plan_ids,
                candidate_rows,
            )
            visual_rollback_plan_ids.update(visual_non_replaced_plan_ids)
        recommended_rollback_plan_ids = rollback_plan_ids | external_rollback_plan_ids | visual_rollback_plan_ids
        if recommended_rollback_plan_ids:
            safe_rows = _copy_plan_rows(candidate_rows)
            safe_rows = _rollback_release_rows(safe_rows, rollback_plan_ids | external_rollback_plan_ids)
            safe_rows = _rollback_visual_conflict_release_rows(safe_rows, visual_rollback_plan_ids)
            topology_safe_plan = _write_plan_json(artifacts.step_root, safe_rows, "topology_safe")
            artifacts = _run_step3(
                step2_replaceable_path=step2_replaceable_path,
                step2_special_junction_group_audit_path=step2_special_junction_group_audit_path,
                step2_group_replacement_audit_path=step2_group_replacement_audit_path,
                step2_replacement_plan_path=topology_safe_plan,
                swsd_segment_path=swsd_segment_path,
                swsd_roads_path=swsd_roads_path,
                swsd_nodes_path=swsd_nodes_path,
                rcsdroad_path=rcsdroad_path,
                rcsdnode_path=rcsdnode_path,
                out_root=out_root,
                run_id=run_id,
                junction_surface_path=surface_inputs.get("t05_surface_path"),
                progress=progress,
                write_feature_json_outputs=False,
            )
            full_step3_run_count += 1
            surface_summary = _run_surface(
                artifacts,
                swsd_segment_path=swsd_segment_path,
                swsd_roads_path=swsd_roads_path,
                surface_inputs=surface_inputs,
                surface_topology_closure=surface_topology_closure,
                write_feature_json_outputs=False,
                topology_coverage_cache=topology_coverage_cache,
            )
            final_fail_keys = _topology_fail_keys(artifacts.step_root)
            external_added_fail_keys = final_fail_keys - external_baseline_fail_keys if external_baseline_root else set()
    else:
        final_fail_keys = set(baseline_fail_keys)
        added_fail_keys: set[tuple[str, str, str, str, str]] = set()
        external_added_fail_keys = final_fail_keys - external_baseline_fail_keys if external_baseline_root else set()

    visual_release_audit = None
    if visual_released:
        visual_release_audit = {
            "released_count": len(visual_released),
            "candidate_added_fail_count": len(visual_added_fail_keys),
            "rolled_back_count": len(visual_rollback_plan_ids),
            "non_replaced_rolled_back_count": len(visual_non_replaced_plan_ids),
            "final_added_fail_count": len(final_fail_keys - rollback_reference_fail_keys),
            "released": visual_released,
            "non_replaced_rolled_back_plan_ids": sorted(visual_non_replaced_plan_ids),
            "rolled_back_plan_ids": sorted(visual_rollback_plan_ids),
        }

    fallback_applied = topology_safe_plan is not None
    final_plan = topology_safe_plan or candidate_plan
    candidate_plan_retired = retire_intermediate_step3_plan(candidate_plan, final_plan)
    if not released and not visual_released:
        status = "skipped_no_surface_release"
    elif external_added_fail_keys:
        status = "applied_with_single_fallback_external_topology_regression"
    elif fallback_applied:
        status = "applied_with_single_fallback"
    else:
        status = "applied_without_fallback"

    audit = {
        "status": status,
        "full_step3_run_count": full_step3_run_count,
        "extra_step3_run_count": max(0, full_step3_run_count - 1),
        "full_output_step3_run_count": full_step3_run_count,
        "validation_step3_run_count": 0,
        "candidate_step3_run_count": 1 if candidate_plan else 0,
        "fallback_step3_run_count": 1 if fallback_applied else 0,
        "max_fallback_step3_run_count": 1,
        "baseline_fail_count": len(baseline_fail_keys),
        "candidate_added_fail_count": len(added_fail_keys),
        "final_fail_count": len(final_fail_keys),
        "final_added_fail_count": len(final_fail_keys - baseline_fail_keys),
        "candidate_plan_path": str(candidate_plan) if candidate_plan and not candidate_plan_retired else None,
        "candidate_plan_retired": candidate_plan_retired,
        "final_plan_path": str(final_plan) if final_plan else None,
        "topology_safe_plan_path": str(topology_safe_plan) if topology_safe_plan else None,
        "external_baseline_path": str(external_baseline_root) if external_baseline_root else None,
        "external_baseline_fail_count": len(external_baseline_fail_keys) if external_baseline_root else None,
        "external_final_added_fail_count": len(external_added_fail_keys),
        "external_final_added_fail_keys": [list(item) for item in sorted(external_added_fail_keys)],
        "released_count": len(released),
        "rolled_back_count": len(rollback_plan_ids) if fallback_applied else 0,
        "rollback_recommended_count": len(rollback_plan_ids),
        "external_rolled_back_count": len(external_rollback_plan_ids) if fallback_applied else 0,
        "external_rollback_recommended_count": len(external_rollback_plan_ids),
        "external_rollback_recommended_plan_ids": sorted(external_rollback_plan_ids),
        "released": released,
        "rolled_back_plan_ids": sorted(rollback_plan_ids) if fallback_applied else [],
        "rollback_recommended_plan_ids": sorted(rollback_plan_ids),
    }
    if visual_release_audit is not None:
        audit["visual_conflict_release"] = visual_release_audit
    _write_release_audit(artifacts.step_root, audit)
    _merge_release_summary(artifacts.summary_path, audit)
    return artifacts, surface_summary


def _run_preplanned_release_step3(
    *,
    plan_rows: list[dict[str, Any]],
    step2_replaceable_path: str | Path,
    step2_special_junction_group_audit_path: str | Path | None,
    step2_group_replacement_audit_path: str | Path | None,
    swsd_segment_path: str | Path,
    swsd_roads_path: str | Path,
    swsd_nodes_path: str | Path,
    rcsdroad_path: str | Path,
    rcsdnode_path: str | Path,
    out_root: str | Path,
    run_id: str | None,
    surface_inputs: dict[str, Path | None],
    surface_topology_closure: bool,
    progress: bool,
    topology_coverage_cache: dict[Any, Any],
) -> tuple[T06Step3Artifacts, dict[str, Any] | None] | None:
    resolved_run_id = run_id or default_run_id()
    step_root = Path(out_root) / resolved_run_id / STEP3_DIR
    step_root.mkdir(parents=True, exist_ok=True)
    incident_segments_by_node = _incident_segments_by_node(read_features(swsd_segment_path))
    release_rows, released = _preplanned_surface_release_plan_rows(
        plan_rows,
        step2_replaceable_path=step2_replaceable_path,
        swsd_segment_path=swsd_segment_path,
        swsd_nodes_path=swsd_nodes_path,
        rcsdnode_path=rcsdnode_path,
        incident_segments_by_node=incident_segments_by_node,
    )
    candidate_rows, visual_released = _visual_conflict_release_plan_rows(_copy_plan_rows(release_rows))
    if not released and not visual_released:
        return None

    candidate_plan = _write_plan_json(step_root, candidate_rows, "candidate")
    external_baseline_root = _external_baseline_step3_root(step2_replaceable_path, step_root)
    external_baseline_fail_keys = _topology_fail_keys(external_baseline_root) if external_baseline_root else set()
    rollback_reference_fail_keys = external_baseline_fail_keys
    artifacts = _run_step3(
        step2_replaceable_path=step2_replaceable_path,
        step2_special_junction_group_audit_path=step2_special_junction_group_audit_path,
        step2_group_replacement_audit_path=step2_group_replacement_audit_path,
        step2_replacement_plan_path=candidate_plan,
        swsd_segment_path=swsd_segment_path,
        swsd_roads_path=swsd_roads_path,
        swsd_nodes_path=swsd_nodes_path,
        rcsdroad_path=rcsdroad_path,
        rcsdnode_path=rcsdnode_path,
        out_root=out_root,
        run_id=resolved_run_id,
        junction_surface_path=surface_inputs.get("t05_surface_path"),
        progress=progress,
        write_feature_json_outputs=False,
    )
    full_step3_run_count = 1
    surface_summary = _run_surface(
        artifacts,
        swsd_segment_path=swsd_segment_path,
        swsd_roads_path=swsd_roads_path,
        surface_inputs=surface_inputs,
        surface_topology_closure=surface_topology_closure,
        write_feature_json_outputs=False,
        topology_coverage_cache=topology_coverage_cache,
    )
    final_fail_keys = _topology_fail_keys(artifacts.step_root)
    added_fail_keys = final_fail_keys - rollback_reference_fail_keys
    rollback_plan_ids: set[str] = set()
    if released:
        rollback_plan_ids = _rollback_plan_ids(
            added_fail_keys,
            released,
            candidate_rows,
            swsd_segment_path,
            incident_segments_by_node=incident_segments_by_node,
        )
    visual_rollback_plan_ids: set[str] = set()
    visual_non_replaced_plan_ids: set[str] = set()
    visual_added_fail_keys: set[tuple[str, str, str, str, str]] = set()
    if visual_released:
        surface_safe_fail_keys = _fail_keys_after_release_rollback(
            final_fail_keys,
            released,
            rollback_plan_ids,
            incident_segments_by_node,
        )
        visual_added_fail_keys = surface_safe_fail_keys - rollback_reference_fail_keys
        visual_non_replaced_plan_ids = _visual_conflict_non_replaced_plan_ids(artifacts.step_root, visual_released)
        visual_rollback_plan_ids = _visual_conflict_rollback_plan_ids(
            visual_added_fail_keys,
            visual_released,
            swsd_segment_path,
            incident_segments_by_node=incident_segments_by_node,
        )
        visual_rollback_plan_ids = _filter_visual_topology_rollback_plan_ids(
            visual_rollback_plan_ids,
            candidate_rows,
        )
        visual_rollback_plan_ids.update(visual_non_replaced_plan_ids)

    topology_safe_plan: Path | None = None
    recommended_rollback_plan_ids = rollback_plan_ids | visual_rollback_plan_ids
    if recommended_rollback_plan_ids:
        safe_rows = _copy_plan_rows(candidate_rows)
        safe_rows = _rollback_release_rows(safe_rows, rollback_plan_ids)
        safe_rows = _rollback_visual_conflict_release_rows(safe_rows, visual_rollback_plan_ids)
        topology_safe_plan = _write_plan_json(artifacts.step_root, safe_rows, "topology_safe")
        artifacts = _run_step3(
            step2_replaceable_path=step2_replaceable_path,
            step2_special_junction_group_audit_path=step2_special_junction_group_audit_path,
            step2_group_replacement_audit_path=step2_group_replacement_audit_path,
            step2_replacement_plan_path=topology_safe_plan,
            swsd_segment_path=swsd_segment_path,
            swsd_roads_path=swsd_roads_path,
            swsd_nodes_path=swsd_nodes_path,
            rcsdroad_path=rcsdroad_path,
            rcsdnode_path=rcsdnode_path,
            out_root=out_root,
            run_id=resolved_run_id,
            junction_surface_path=surface_inputs.get("t05_surface_path"),
            progress=progress,
            write_feature_json_outputs=False,
        )
        full_step3_run_count += 1
        surface_summary = _run_surface(
            artifacts,
            swsd_segment_path=swsd_segment_path,
            swsd_roads_path=swsd_roads_path,
            surface_inputs=surface_inputs,
            surface_topology_closure=surface_topology_closure,
            write_feature_json_outputs=False,
            topology_coverage_cache=topology_coverage_cache,
        )
        final_fail_keys = _topology_fail_keys(artifacts.step_root)

    candidate_plan_retired = retire_intermediate_step3_plan(candidate_plan, topology_safe_plan or candidate_plan)
    visual_release_audit = None
    if visual_released:
        visual_release_audit = {
            "released_count": len(visual_released),
            "candidate_added_fail_count": len(visual_added_fail_keys),
            "rolled_back_count": len(visual_rollback_plan_ids),
            "non_replaced_rolled_back_count": len(visual_non_replaced_plan_ids),
            "final_added_fail_count": len(final_fail_keys - rollback_reference_fail_keys),
            "released": visual_released,
            "non_replaced_rolled_back_plan_ids": sorted(visual_non_replaced_plan_ids),
            "rolled_back_plan_ids": sorted(visual_rollback_plan_ids),
        }
    fallback_applied = topology_safe_plan is not None
    audit = {
        "status": "preplanned_with_single_fallback" if fallback_applied else "preplanned_without_fallback",
        "preplanned_release": True,
        "full_step3_run_count": full_step3_run_count,
        "extra_step3_run_count": max(0, full_step3_run_count - 1),
        "full_output_step3_run_count": full_step3_run_count,
        "validation_step3_run_count": 0,
        "candidate_step3_run_count": 1,
        "fallback_step3_run_count": 1 if fallback_applied else 0,
        "max_fallback_step3_run_count": 1,
        "baseline_fail_count": None,
        "candidate_added_fail_count": len(added_fail_keys),
        "final_fail_count": len(final_fail_keys),
        "final_added_fail_count": len(final_fail_keys - rollback_reference_fail_keys),
        "candidate_plan_path": str(candidate_plan) if not candidate_plan_retired else None,
        "candidate_plan_retired": candidate_plan_retired,
        "final_plan_path": str(topology_safe_plan or candidate_plan),
        "topology_safe_plan_path": str(topology_safe_plan) if topology_safe_plan else None,
        "external_baseline_path": str(external_baseline_root) if external_baseline_root else None,
        "external_baseline_fail_count": len(external_baseline_fail_keys) if external_baseline_root else None,
        "external_final_added_fail_count": len(final_fail_keys - external_baseline_fail_keys) if external_baseline_root else None,
        "external_final_added_fail_keys": [list(item) for item in sorted(final_fail_keys - external_baseline_fail_keys)] if external_baseline_root else [],
        "released_count": len(released),
        "rolled_back_count": len(rollback_plan_ids) if fallback_applied else 0,
        "rollback_recommended_count": len(rollback_plan_ids),
        "external_rolled_back_count": 0,
        "external_rollback_recommended_count": 0,
        "external_rollback_recommended_plan_ids": [],
        "released": released,
        "rolled_back_plan_ids": sorted(rollback_plan_ids) if fallback_applied else [],
        "rollback_recommended_plan_ids": sorted(rollback_plan_ids),
    }
    if visual_release_audit is not None:
        audit["visual_conflict_release"] = visual_release_audit
    _write_release_audit(artifacts.step_root, audit)
    _merge_release_summary(artifacts.summary_path, audit)
    return artifacts, surface_summary


def _run_step3(
    *,
    write_feature_json_outputs: bool = True,
    **kwargs: Any,
) -> T06Step3Artifacts:
    if write_feature_json_outputs:
        return run_t06_step3_segment_replacement(**kwargs)
    with suppress_feature_json_outputs():
        return run_t06_step3_segment_replacement(**kwargs)


def _run_surface(
    artifacts: T06Step3Artifacts,
    *,
    swsd_segment_path: str | Path,
    swsd_roads_path: str | Path,
    surface_inputs: dict[str, Path | None],
    surface_topology_closure: bool,
    write_feature_json_outputs: bool = True,
    topology_coverage_cache: dict[Any, Any] | None = None,
) -> dict[str, Any] | None:
    if not any(surface_inputs.values()):
        return None
    if write_feature_json_outputs:
        summary = _run_surface_topology_postprocess(
            artifacts=artifacts,
            swsd_segment_path=swsd_segment_path,
            swsd_roads_path=swsd_roads_path,
            surface_inputs=surface_inputs,
            surface_topology_closure=surface_topology_closure,
            topology_coverage_cache=topology_coverage_cache,
        )
    else:
        with suppress_feature_json_outputs():
            summary = _run_surface_topology_postprocess(
                artifacts=artifacts,
                swsd_segment_path=swsd_segment_path,
                swsd_roads_path=swsd_roads_path,
                surface_inputs=surface_inputs,
                surface_topology_closure=surface_topology_closure,
                topology_coverage_cache=topology_coverage_cache,
            )
    semantic_stats = refresh_semantic_junction_topology_audit(step_root=artifacts.step_root, summary_path=artifacts.summary_path)
    if summary is not None:
        summary["semantic_junction_topology_refresh"] = semantic_stats
    return summary


def _run_surface_topology_postprocess(
    *,
    artifacts: T06Step3Artifacts,
    swsd_segment_path: str | Path,
    swsd_roads_path: str | Path,
    surface_inputs: dict[str, Path | None],
    surface_topology_closure: bool,
    topology_coverage_cache: dict[Any, Any] | None = None,
) -> dict[str, Any]:
    return run_surface_topology_postprocess(
        step_root=artifacts.step_root,
        swsd_segment_path=swsd_segment_path,
        swsd_roads_path=swsd_roads_path,
        t07_surface_path=surface_inputs.get("t07_surface_path"),
        t03_surface_path=surface_inputs.get("t03_surface_path"),
        t04_surface_path=surface_inputs.get("t04_surface_path"),
        t04_audit_path=surface_inputs.get("t04_audit_path"),
        t05_surface_path=surface_inputs.get("t05_surface_path"),
        apply_closure=surface_topology_closure,
        topology_coverage_cache=topology_coverage_cache,
    )

def _surface_release_plan_rows(
    plan_rows: list[dict[str, Any]],
    *,
    step_root: Path,
    swsd_segment_path: str | Path,
    swsd_nodes_path: str | Path,
    rcsdnode_path: str | Path,
    incident_segments_by_node: dict[str, list[str]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    surface_status = _surface_status_by_node(step_root)
    swsd_node_rows = read_features(swsd_nodes_path)
    swsd_points = _points_by_id(swsd_node_rows)
    swsd_fallback_points = _fallback_points_by_id(swsd_node_rows)
    swsd_anchor_nodes = _anchor_node_ids(swsd_node_rows)
    rcsd_node_rows = read_features(rcsdnode_path)
    rcsd_points = _points_by_id(rcsd_node_rows)
    rcsd_fallback_points = _fallback_points_by_id(rcsd_node_rows)
    t05_relation_by_target = _t05_relation_targets_for_step(step_root)
    rcsd_semantic_ids_by_node = _semantic_ids_by_node(rcsd_node_rows)
    incident = incident_segments_by_node
    if incident is None:
        incident = _incident_segments_by_node(read_features(swsd_segment_path))
    ready_segments = _ready_segment_ids(plan_rows)
    released: list[dict[str, Any]] = []
    rows = [{"properties": dict(row.get("properties") or {}), "geometry": row.get("geometry")} for row in plan_rows]
    for row in rows:
        props = row["properties"]
        if not _is_retained_junction_gate_plan(props):
            continue
        allow, triggers = _release_allowed(
            props,
            surface_status,
            swsd_points,
            rcsd_points,
            incident,
            ready_segments,
            swsd_anchor_nodes,
            swsd_fallback_points=swsd_fallback_points,
            rcsd_fallback_points=rcsd_fallback_points,
            t05_relation_by_target=t05_relation_by_target,
            rcsd_semantic_ids_by_node=rcsd_semantic_ids_by_node,
        )
        if not allow:
            continue
        _release_plan_row(props)
        released.append(
            {
                "plan_id": props.get("replacement_plan_id"),
                "segment_id": props.get("swsd_segment_id"),
                "scope": props.get("execution_scope"),
                "group_segment_ids": _ids(props.get("group_segment_ids")),
                "triggers": triggers,
            }
        )
    return rows, released


def _preplanned_surface_release_plan_rows(
    plan_rows: list[dict[str, Any]],
    *,
    step2_replaceable_path: str | Path,
    swsd_segment_path: str | Path,
    swsd_nodes_path: str | Path,
    rcsdnode_path: str | Path,
    incident_segments_by_node: dict[str, list[str]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    swsd_node_rows = read_features(swsd_nodes_path)
    swsd_points = _points_by_id(swsd_node_rows)
    swsd_fallback_points = _fallback_points_by_id(swsd_node_rows)
    swsd_anchor_nodes = _anchor_node_ids(swsd_node_rows)
    rcsd_node_rows = read_features(rcsdnode_path)
    rcsd_points = _points_by_id(rcsd_node_rows)
    rcsd_fallback_points = _fallback_points_by_id(rcsd_node_rows)
    relation_path = discover_intersection_match_path(step2_replaceable_path)
    t05_relation_by_target = valid_t05_relation_targets(relation_path) if relation_path else {}
    rcsd_semantic_ids_by_node = _semantic_ids_by_node(rcsd_node_rows)
    incident = incident_segments_by_node
    if incident is None:
        incident = _incident_segments_by_node(read_features(swsd_segment_path))
    ready_segments = _ready_segment_ids(plan_rows)
    released: list[dict[str, Any]] = []
    rows = [{"properties": dict(row.get("properties") or {}), "geometry": row.get("geometry")} for row in plan_rows]
    for row in rows:
        props = row["properties"]
        if not _is_retained_junction_gate_plan(props):
            continue
        allow, triggers = _release_allowed(
            props,
            {},
            swsd_points,
            rcsd_points,
            incident,
            ready_segments,
            swsd_anchor_nodes,
            swsd_fallback_points=swsd_fallback_points,
            rcsd_fallback_points=rcsd_fallback_points,
            t05_relation_by_target=t05_relation_by_target,
            rcsd_semantic_ids_by_node=rcsd_semantic_ids_by_node,
        )
        if not allow or not _preplanned_release_triggers_allowed(triggers):
            continue
        _release_plan_row(props)
        released.append(
            {
                "plan_id": props.get("replacement_plan_id"),
                "segment_id": props.get("swsd_segment_id"),
                "scope": props.get("execution_scope"),
                "group_segment_ids": _ids(props.get("group_segment_ids")),
                "triggers": triggers,
                "preplanned": True,
            }
        )
    return rows, released


def _preplanned_release_triggers_allowed(triggers: list[dict[str, Any]]) -> bool:
    allowed_reasons = {
        T05_SEMANTIC_JUNCTION_RELEASE_REASON,
        OPTIONAL_JUNCTION_ANCHOR_RELEASE_REASON,
        "auto_closed_selected_replacement_endpoint",
    }
    for trigger in triggers:
        status = trigger.get("surface_status")
        reason = status[1] if isinstance(status, list) and len(status) > 1 else None
        if reason not in allowed_reasons:
            return False
    return bool(triggers)


def _release_allowed(
    props: dict[str, Any],
    surface_status: dict[str, tuple[str, str, Any]],
    swsd_points: dict[str, Any],
    rcsd_points: dict[str, Any],
    incident: dict[str, list[str]],
    ready_segments: set[str],
    swsd_anchor_nodes: set[str] | None = None,
    swsd_fallback_points: dict[str, Any] | None = None,
    rcsd_fallback_points: dict[str, Any] | None = None,
    t05_relation_by_target: dict[str, str] | None = None,
    rcsd_semantic_ids_by_node: dict[str, set[str]] | None = None,
) -> tuple[bool, list[dict[str, Any]]]:
    scope = props.get("execution_scope")
    if scope and scope != "standard_segment":
        return False, []
    if not _is_retained_junction_gate_plan(props):
        return False, []
    swsd_anchor_nodes = swsd_anchor_nodes or set()
    t05_relation_by_target = t05_relation_by_target or {}
    rcsd_semantic_ids_by_node = rcsd_semantic_ids_by_node or {}
    triggers: list[dict[str, Any]] = []
    for swsd_node_id, rcsd_node_id in _plan_mappings(props):
        if not any(segment_id not in ready_segments for segment_id in incident.get(swsd_node_id, [])):
            continue
        trigger = _release_trigger_for_mapping(
            props,
            swsd_node_id=swsd_node_id,
            rcsd_node_id=rcsd_node_id,
            swsd_points=swsd_points,
            rcsd_points=rcsd_points,
            surface_status=surface_status,
            swsd_anchor_nodes=swsd_anchor_nodes,
            t05_relation_by_target=t05_relation_by_target,
            rcsd_semantic_ids_by_node=rcsd_semantic_ids_by_node,
        )
        if trigger is None:
            trigger = _release_trigger_for_mapping(
                props,
                swsd_node_id=swsd_node_id,
                rcsd_node_id=rcsd_node_id,
                swsd_points=swsd_fallback_points or {},
                rcsd_points=rcsd_fallback_points or {},
                surface_status=surface_status,
                swsd_anchor_nodes=swsd_anchor_nodes,
                point_source="mainnodeid_fallback",
                t05_relation_by_target=t05_relation_by_target,
                rcsd_semantic_ids_by_node=rcsd_semantic_ids_by_node,
            )
        if trigger is None:
            continue
        triggers.append(trigger)
    return bool(triggers) and all(item["ok"] for item in triggers), triggers


def _release_trigger_for_mapping(
    props: dict[str, Any],
    *,
    swsd_node_id: str,
    rcsd_node_id: str,
    swsd_points: dict[str, Any],
    rcsd_points: dict[str, Any],
    surface_status: dict[str, tuple[str, str, Any]],
    swsd_anchor_nodes: set[str],
    point_source: str | None = None,
    t05_relation_by_target: dict[str, str] | None = None,
    rcsd_semantic_ids_by_node: dict[str, set[str]] | None = None,
) -> dict[str, Any] | None:
    if swsd_node_id not in swsd_points or rcsd_node_id not in rcsd_points:
        return None
    distance_m = float(swsd_points[swsd_node_id].distance(rcsd_points[rcsd_node_id]))
    t05_release = _is_t05_semantic_relation_mapping(
        swsd_node_id,
        rcsd_node_id,
        t05_relation_by_target or {},
        rcsd_semantic_ids_by_node or {},
    )
    status = surface_status.get(swsd_node_id)
    if t05_release:
        ok = True
        release_status = ["pass", T05_SEMANTIC_JUNCTION_RELEASE_REASON, round(distance_m, 3)]
    elif distance_m <= RETAINED_JUNCTION_ATTACHMENT_GAP_M:
        return None
    elif status:
        ok = bool(status[0] == "pass" and status[1] in SURFACE_RELEASE_REASONS)
        release_status = list(status)
    elif _is_original_pair_endpoint_mapping(props, swsd_node_id, rcsd_node_id):
        ok = True
        release_status = ["pass", "auto_closed_selected_replacement_endpoint", round(distance_m, 3)]
    elif _is_optional_junc_anchor_mapping(props, swsd_node_id, rcsd_node_id, swsd_anchor_nodes, distance_m):
        ok = True
        release_status = ["pass", OPTIONAL_JUNCTION_ANCHOR_RELEASE_REASON, round(distance_m, 3)]
    else:
        ok = False
        release_status = None
    trigger = {
        "swsd_node_id": swsd_node_id,
        "rcsd_node_id": rcsd_node_id,
        "distance_m": round(distance_m, 3),
        "surface_status": release_status,
        "ok": ok,
    }
    if point_source:
        trigger["point_source"] = point_source
    return trigger


def _is_t05_semantic_relation_mapping(
    swsd_node_id: str,
    rcsd_node_id: str,
    t05_relation_by_target: dict[str, str],
    rcsd_semantic_ids_by_node: dict[str, set[str]],
) -> bool:
    base_id = t05_relation_by_target.get(swsd_node_id)
    if not base_id:
        return False
    semantic_ids = rcsd_semantic_ids_by_node.get(rcsd_node_id, {rcsd_node_id})
    return base_id in semantic_ids


def _is_retained_junction_gate_plan(props: dict[str, Any]) -> bool:
    return props.get("source_reason") == RETAINED_JUNCTION_GATE_REASON or RETAINED_JUNCTION_GATE_REASON in set(_ids(props.get("risk_flags")))


def _is_original_pair_endpoint_mapping(props: dict[str, Any], swsd_node_id: str, rcsd_node_id: str) -> bool:
    swsd_pair_nodes = _ids(props.get("swsd_pair_nodes"))
    original_rcsd_pair_nodes = _ids(props.get("original_rcsd_pair_nodes"))
    if len(swsd_pair_nodes) != len(original_rcsd_pair_nodes):
        return False
    return any(swsd_node_id == swsd and rcsd_node_id == rcsd for swsd, rcsd in zip(swsd_pair_nodes, original_rcsd_pair_nodes))


def _is_optional_junc_anchor_mapping(
    props: dict[str, Any],
    swsd_node_id: str,
    rcsd_node_id: str,
    swsd_anchor_nodes: set[str],
    distance_m: float,
) -> bool:
    if swsd_node_id not in swsd_anchor_nodes or distance_m > OPTIONAL_JUNCTION_ANCHOR_RELEASE_MAX_GAP_M:
        return False
    swsd_junc = _ids(props.get("optional_junc_nodes")) or _ids(props.get("swsd_junc_nodes"))
    rcsd_junc = _ids(props.get("optional_junc_rcsd_nodes")) or _ids(props.get("rcsd_junc_nodes"))
    return any(swsd_node_id == swsd and rcsd_node_id == rcsd for swsd, rcsd in zip(swsd_junc, rcsd_junc))


def _release_plan_row(props: dict[str, Any]) -> None:
    props["plan_status"] = "ready"
    props["execution_action"] = "replace"
    if props.get("execution_scope") == "path_corridor_group":
        props["source_reason"] = "passed"
    else:
        props["source_reason"] = props.get("replacement_strategy") or "buffer_segment_extraction"
    props["risk_flags"] = unique_preserve_order([*_ids(props.get("risk_flags")), RETAINED_JUNCTION_GATE_REASON, SURFACE_RELEASE_RISK])
    notes = str(props.get("notes") or "")
    notes = notes.replace(f"; blocked by {RETAINED_JUNCTION_GATE_REASON}", "")
    notes = notes.replace(f"blocked by {RETAINED_JUNCTION_GATE_REASON}", "")
    suffix = f"risk: {RETAINED_JUNCTION_GATE_REASON}; risk: {SURFACE_RELEASE_RISK}"
    props["notes"] = f"{notes.strip('; ')}; {suffix}" if notes.strip("; ") else suffix


def _rollback_release_rows(rows: list[dict[str, Any]], rollback_plan_ids: set[str]) -> list[dict[str, Any]]:
    for row in rows:
        props = row.get("properties") or {}
        if str(props.get("replacement_plan_id") or "") not in rollback_plan_ids:
            continue
        props["plan_status"] = "blocked"
        props["execution_action"] = "hold"
        props["source_reason"] = SURFACE_RELEASE_ROLLBACK_REASON
        props["risk_flags"] = unique_preserve_order([*_ids(props.get("risk_flags")), SURFACE_RELEASE_ROLLBACK_REASON])
        notes = str(props.get("notes") or "")
        suffix = f"blocked by {SURFACE_RELEASE_ROLLBACK_REASON}"
        props["notes"] = f"{notes}; {suffix}" if notes else suffix
    return rows


def _visual_conflict_release_plan_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    released: list[dict[str, Any]] = []
    result = _copy_plan_rows(rows)
    for row in result:
        props = row["properties"]
        if props.get("source_reason") != VISUAL_CONFLICT_REASON or props.get("plan_status") == "ready":
            continue
        _release_visual_conflict_plan_row(props)
        released.append(
            {
                "plan_id": props.get("replacement_plan_id"),
                "segment_id": props.get("swsd_segment_id"),
                "scope": props.get("execution_scope"),
                "group_segment_ids": _ids(props.get("group_segment_ids")),
                "release_reason": VISUAL_CONFLICT_REASON,
            }
        )
    return result, released


def _release_visual_conflict_plan_row(props: dict[str, Any]) -> None:
    props["plan_status"] = "ready"
    props["execution_action"] = "replace"
    props["risk_flags"] = unique_preserve_order([*_ids(props.get("risk_flags")), VISUAL_CONFLICT_REASON, VISUAL_CONFLICT_RELEASE_RISK])
    notes = str(props.get("notes") or "")
    suffix = f"risk: {VISUAL_CONFLICT_REASON}; risk: {VISUAL_CONFLICT_RELEASE_RISK}"
    props["notes"] = f"{notes.strip('; ')}; {suffix}" if notes.strip("; ") else suffix


def _rollback_visual_conflict_release_rows(rows: list[dict[str, Any]], rollback_plan_ids: set[str]) -> list[dict[str, Any]]:
    for row in rows:
        props = row.get("properties") or {}
        if str(props.get("replacement_plan_id") or "") not in rollback_plan_ids:
            continue
        if VISUAL_CONFLICT_RELEASE_RISK not in set(_ids(props.get("risk_flags"))):
            continue
        props["plan_status"] = "blocked"
        props["execution_action"] = "hold"
        props["source_reason"] = VISUAL_CONFLICT_REASON
        props["risk_flags"] = unique_preserve_order([*_ids(props.get("risk_flags")), VISUAL_CONFLICT_ROLLBACK_REASON])
        notes = str(props.get("notes") or "")
        suffix = f"blocked by {VISUAL_CONFLICT_ROLLBACK_REASON}"
        props["notes"] = f"{notes}; {suffix}" if notes else suffix
    return rows


def _visual_conflict_rollback_plan_ids(
    added_fail_keys: set[tuple[str, str, str, str, str]],
    released: list[dict[str, Any]],
    swsd_segment_path: str | Path,
    incident_segments_by_node: dict[str, list[str]] | None = None,
) -> set[str]:
    incident = incident_segments_by_node
    if incident is None:
        incident = _incident_segments_by_node(read_features(swsd_segment_path))
    return _rollback_plan_ids_for_failed_segments(_visual_conflict_rollback_fail_keys(added_fail_keys), released, incident)


def _filter_visual_topology_rollback_plan_ids(
    rollback_plan_ids: set[str],
    plan_rows: list[dict[str, Any]],
) -> set[str]:
    if not rollback_plan_ids:
        return set()
    rows_by_plan_id = {
        str((row.get("properties") or {}).get("replacement_plan_id") or ""): row.get("properties") or {}
        for row in plan_rows
    }
    result: set[str] = set()
    for plan_id in rollback_plan_ids:
        props = rows_by_plan_id.get(plan_id) or {}
        if _float_value(props.get("swsd_uncovered_by_rcsd_ratio")) > 0.0:
            result.add(plan_id)
    return result


def _visual_conflict_rollback_fail_keys(
    added_fail_keys: set[tuple[str, str, str, str, str]],
) -> set[tuple[str, str, str, str, str]]:
    return {
        key
        for key in added_fail_keys
        if not (key[0] == "advance_right_endpoint_connectivity" and key[4] == "advance_right_leaf_endpoint_unattached")
    }


def _surface_release_rollback_eligible_items(released: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in released if not _is_t05_semantic_surface_release(item)]


def _float_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _is_t05_semantic_surface_release(item: dict[str, Any]) -> bool:
    triggers = [trigger for trigger in item.get("triggers") or [] if isinstance(trigger, dict)]
    if not triggers:
        return False
    for trigger in triggers:
        status = trigger.get("surface_status")
        if not isinstance(status, list) or len(status) < 2 or status[1] != T05_SEMANTIC_JUNCTION_RELEASE_REASON:
            return False
    return True


def _visual_conflict_non_replaced_plan_ids(step_root: Path, released: list[dict[str, Any]]) -> set[str]:
    relation_path = step_root / f"{STEP3_SWSD_FRCSD_SEGMENT_RELATION_STEM}.gpkg"
    if not relation_path.is_file():
        return set()
    status_by_segment: dict[str, str] = {}
    for row in read_features(relation_path):
        props = row.get("properties") or {}
        segment_id = str(props.get("swsd_segment_id") or "")
        if segment_id:
            status_by_segment[segment_id] = str(props.get("relation_status") or "")
    result: set[str] = set()
    for item in released:
        plan_id = str(item.get("plan_id") or "")
        if not plan_id:
            continue
        segment_ids = {str(item.get("segment_id") or ""), *_ids(item.get("group_segment_ids"))}
        segment_ids.discard("")
        if not any(_is_successful_replacement_status(status_by_segment.get(segment_id)) for segment_id in segment_ids):
            result.add(plan_id)
    return result


def _is_successful_replacement_status(status: str | None) -> bool:
    return str(status or "") in {"replaced", "replaced+retained_swsd"}


def _rollback_plan_ids(
    added_fail_keys: set[tuple[str, str, str, str, str]],
    released: list[dict[str, Any]],
    _plan_rows: list[dict[str, Any]],
    swsd_segment_path: str | Path,
    incident_segments_by_node: dict[str, list[str]] | None = None,
) -> set[str]:
    incident = incident_segments_by_node
    if incident is None:
        incident = _incident_segments_by_node(read_features(swsd_segment_path))
    return _rollback_plan_ids_for_failed_segments(
        added_fail_keys,
        _surface_release_rollback_eligible_items(released),
        incident,
    )


def _fail_keys_after_release_rollback(
    fail_keys: set[tuple[str, str, str, str, str]],
    released: list[dict[str, Any]],
    rollback_plan_ids: set[str],
    incident: dict[str, list[str]],
) -> set[tuple[str, str, str, str, str]]:
    if not fail_keys or not rollback_plan_ids:
        return set(fail_keys)
    eligible = _surface_release_rollback_eligible_items(released)
    retained: set[tuple[str, str, str, str, str]] = set()
    for fail_key in fail_keys:
        related_plan_ids = _rollback_plan_ids_for_failed_segments({fail_key}, eligible, incident)
        if related_plan_ids.intersection(rollback_plan_ids):
            continue
        retained.add(fail_key)
    return retained


def _rollback_items_for_plan_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in rows:
        props = row.get("properties") or {}
        plan_id = str(props.get("replacement_plan_id") or "")
        if not plan_id:
            continue
        items.append(
            {
                "plan_id": plan_id,
                "segment_id": str(props.get("swsd_segment_id") or ""),
                "group_segment_ids": _ids(props.get("group_segment_ids")),
            }
        )
    return items


def _rollback_plan_ids_for_failed_segments(
    added_fail_keys: set[tuple[str, str, str, str, str]],
    released: list[dict[str, Any]],
    incident: dict[str, list[str]],
) -> set[str]:
    if not added_fail_keys:
        return set()
    failed_segments: set[str] = set()
    for _layer, segment_id, node_id, _road_id, _reason in added_fail_keys:
        segment_ids = _ids(segment_id)
        if segment_ids:
            failed_segments.update(segment_ids)
        elif segment_id:
            failed_segments.add(segment_id)
        if node_id and not (segment_ids or segment_id):
            failed_segments.update(incident.get(node_id, []))
    result: set[str] = set()
    for item in released:
        plan_id = str(item.get("plan_id") or "")
        if not plan_id:
            continue
        segment_ids = {str(item.get("segment_id") or ""), *_ids(item.get("group_segment_ids"))}
        segment_ids.discard("")
        if segment_ids.intersection(failed_segments):
            result.add(plan_id)
    return result


def _surface_status_by_node(step_root: Path) -> dict[str, tuple[str, str, Any]]:
    path = step_root / "t06_step3_surface_topology_audit.gpkg"
    if not path.is_file():
        return {}
    result: dict[str, tuple[str, str, Any]] = {}
    for row in read_features(path):
        props = row.get("properties") or {}
        node_id = str(props.get("swsd_node_id") or "")
        if node_id:
            result[node_id] = (str(props.get("audit_status") or ""), str(props.get("audit_reason") or ""), props.get("max_pairwise_distance_m"))
    return result


def _t05_relation_targets_for_step(step_root: Path) -> dict[str, str]:
    step2_replaceable_path = _summary_input_path(step_root / "t06_step3_summary.json", "step2_replaceable_path")
    if step2_replaceable_path is None:
        return {}
    relation_path = discover_intersection_match_path(step2_replaceable_path)
    if relation_path is None:
        return {}
    return valid_t05_relation_targets(relation_path)


def _semantic_ids_by_node(rows: list[dict[str, Any]]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for row in rows:
        exact_ids = _feature_exact_ids(row)
        if not exact_ids:
            continue
        node_id = exact_ids[0]
        result[node_id] = set(_feature_ids(row))
    return result


def _topology_fail_keys(step_root: Path) -> set[tuple[str, str, str, str, str]]:
    path = step_root / f"{STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM}.gpkg"
    if not path.is_file():
        return set()
    result: set[tuple[str, str, str, str, str]] = set()
    for row in read_features(path):
        props = row.get("properties") or {}
        if props.get("audit_status") != "fail":
            continue
        segment_ids = _ids(props.get("swsd_segment_ids"))
        segment_id = str(props.get("swsd_segment_id") or "")
        if not segment_id and segment_ids:
            segment_id = json.dumps(segment_ids, ensure_ascii=False)
        result.add(
            (
                str(props.get("audit_layer") or ""),
                segment_id,
                str(props.get("swsd_node_id") or ""),
                str(props.get("frcsd_road_id") or ""),
                str(props.get("audit_reason") or ""),
            )
        )
    return result


def _write_plan_json(step_root: Path, rows: list[dict[str, Any]], label: str) -> Path:
    path = step_root / f"{SURFACE_RELEASE_PLAN_STEM}_{label}.json"
    write_json(path, {"row_count": len(rows), "features": rows})
    return path


def _copy_plan_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    copied: list[dict[str, Any]] = []
    for row in rows:
        properties = {
            key: value
            for key, value in dict(row.get("properties") or {}).items()
            if value is not None and key != "absorbed_group_member_segments"
        }
        copied.append(
            {
                "type": row.get("type", "Feature"),
                "properties": properties,
                "geometry": row.get("geometry"),
            }
        )
    return copied


def _write_release_audit(step_root: Path, payload: dict[str, Any]) -> None:
    write_json(step_root / SURFACE_RELEASE_AUDIT, payload)


def _merge_release_summary(summary_path: Path, audit: dict[str, Any]) -> None:
    if not summary_path.is_file():
        return
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    payload["surface_aware_plan_release"] = audit
    outputs = dict(payload.get("outputs") or {})
    outputs["surface_aware_plan_release_audit_json"] = str(summary_path.parent / SURFACE_RELEASE_AUDIT)
    payload["outputs"] = outputs
    write_json(summary_path, payload)


def _summary_input_path(summary_path: Path, key: str) -> Path | None:
    if not summary_path.is_file():
        return None
    value = (json.loads(summary_path.read_text(encoding="utf-8")).get("input_paths") or {}).get(key)
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else Path.cwd() / path


def _preflight_replacement_plan_rows(step2_replaceable_path: str | Path) -> list[dict[str, Any]]:
    step2_root = Path(step2_replaceable_path).resolve().parent
    plan_path = step2_root / f"{STEP2_REPLACEMENT_PLAN_STEM}.gpkg"
    if not plan_path.is_file():
        return []
    return read_features(plan_path)


def _external_baseline_step3_root(step2_replaceable_path: str | Path, current_step_root: Path) -> Path | None:
    step2_root = Path(step2_replaceable_path).resolve().parent
    run_root = step2_root.parent
    candidate = run_root / "step3_segment_replacement"
    if candidate.resolve() == current_step_root.resolve():
        return None
    path = candidate / f"{STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM}.gpkg"
    return candidate if path.is_file() else None


def _points_by_id(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for row in rows:
        geom = row.get("geometry")
        if geom is None:
            continue
        for item_id in _feature_exact_ids(row):
            result[item_id] = geom
    for row in rows:
        geom = row.get("geometry")
        if geom is None:
            continue
        for item_id in _feature_fallback_ids(row):
            result.setdefault(item_id, geom)
    return result


def _fallback_points_by_id(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for row in rows:
        geom = row.get("geometry")
        if geom is None:
            continue
        for item_id in _feature_fallback_ids(row):
            result[item_id] = geom
    return result


def _incident_segments_by_node(segments: list[dict[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for segment in segments:
        props = segment.get("properties") or {}
        segment_id = _feature_id(segment)
        for node_id in unique_preserve_order([*_ids(props.get("pair_nodes")), *_ids(props.get("junc_nodes"))]):
            result[node_id] = unique_preserve_order([*result.get(node_id, []), segment_id])
    return result


def _ready_segment_ids(rows: list[dict[str, Any]]) -> set[str]:
    result: set[str] = set()
    for row in rows:
        props = row.get("properties") or {}
        if props.get("plan_status") != "ready":
            continue
        if props.get("execution_scope") == "path_corridor_group":
            result.update(_ids(props.get("group_segment_ids")))
        elif props.get("swsd_segment_id"):
            result.add(str(props.get("swsd_segment_id")))
    return result


def _plan_mappings(props: dict[str, Any]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for swsd_node_id, rcsd_node_id in zip(_ids(props.get("swsd_pair_nodes")), _ids(props.get("rcsd_pair_nodes"))):
        result.append((swsd_node_id, rcsd_node_id))
    swsd_junc = _ids(props.get("optional_junc_nodes")) or _ids(props.get("swsd_junc_nodes"))
    rcsd_junc = _ids(props.get("optional_junc_rcsd_nodes")) or _ids(props.get("rcsd_junc_nodes"))
    for swsd_node_id, rcsd_node_id in zip(swsd_junc, rcsd_junc):
        result.append((swsd_node_id, rcsd_node_id))
    return result


def _feature_id(feature: dict[str, Any]) -> str:
    ids = _feature_ids(feature)
    return ids[0] if ids else ""


def _feature_ids(feature: dict[str, Any]) -> list[str]:
    return unique_preserve_order([*_feature_exact_ids(feature), *_feature_fallback_ids(feature)])


def _feature_exact_ids(feature: dict[str, Any]) -> list[str]:
    props = feature.get("properties") or {}
    return unique_preserve_order(
        str(value)
        for value in (props.get("id"), props.get("node_id"), props.get("swsd_segment_id"))
        if value not in (None, "")
    )


def _feature_fallback_ids(feature: dict[str, Any]) -> list[str]:
    props = feature.get("properties") or {}
    return unique_preserve_order(
        str(value)
        for value in (props.get("mainnodeid"),)
        if value not in (None, "")
    )


def _anchor_node_ids(rows: list[dict[str, Any]]) -> set[str]:
    result: set[str] = set()
    for row in rows:
        props = row.get("properties") or {}
        if not _truthy_anchor(props.get("is_anchor")):
            continue
        result.update(_feature_ids(row))
    result.discard("")
    return result


def _truthy_anchor(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _ids(value: Any) -> list[str]:
    try:
        return parse_id_list(value)
    except Exception:
        if isinstance(value, list):
            return [str(item) for item in value if str(item)]
        return []
