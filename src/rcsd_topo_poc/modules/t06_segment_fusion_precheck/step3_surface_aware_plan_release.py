from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from .io import (
    default_run_id,
    preserve_read_features_cache,
    read_features,
    suppress_feature_json_outputs,
    write_json,
)
from .rcsd_road_ownership import refresh_rcsd_road_ownership_after_surface
from .segment_construction_audit import refresh_segment_construction_audit_after_surface
from .step3_final_topology_gate import (
    block_final_topology_gate_rows,
    fail_keys_after_plan_rollback as _fail_keys_after_postplan_rollback,
    final_topology_gate_decision,
    postplan_anchor_added_fail_keys as _postplan_anchor_added_fail_keys,
    rollback_items_for_plan_rows as _rollback_items_for_plan_rows,
    rollback_plan_ids_for_failed_segments as _rollback_plan_ids_for_failed_segments,
    topology_fail_keys,
)
from .parsing import unique_preserve_order
from .schemas import (
    STEP2_REPLACEMENT_PLAN_STEM,
    STEP3_DIR,
    STEP3_SWSD_FRCSD_SEGMENT_RELATION_STEM,
)
from .step3_semantic_junction_groups import (
    refresh_semantic_junction_topology_audit,
)
from .step3_output_slimming import retire_intermediate_step3_plan
from .step3_corridor_coverage_cache import preserve_corridor_coverage_decisions
from .step3_replacement_plan_reader import (
    copy_replacement_plan_rows as _copy_plan_rows,
    defer_replacement_plan_writes,
    materialize_deferred_replacement_plan,
    read_replacement_plan_rows,
    write_replacement_plan_json,
)
from .step3_segment_replacement import T06Step3Artifacts, run_t06_step3_segment_replacement
from .step3_topology_connectivity_audit import STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM
from .step3_topology_connectivity_support import _ReusableCoverageCache
from .step3_surface_topology_audit import run_surface_topology_postprocess
from .step3_validation_output_deferred import publish_deferred_validation_outputs
from .step3_surface_runtime import (
    Step3SurfaceRuntimeState,
    normalize_step3_surface_runtime_state,
    take_step3_surface_runtime_state,
)
from .step3_validation_publish import (
    decision_only_validation_step3_run,
    defer_step3_auxiliary_audits,
    defer_step3_initial_topology_audit,
    promote_validation_step3_outputs,
    validation_step3_run,
)
from .step3_surface_release_plan import (
    OPTIONAL_JUNCTION_ANCHOR_RELEASE_MAX_GAP_M,
    OPTIONAL_JUNCTION_ANCHOR_RELEASE_REASON,
    POSTPLAN_ANCHOR_GATE_RISK,
    POSTPLAN_ANCHOR_ROLLBACK_REASON,
    RETAINED_JUNCTION_ATTACHMENT_GAP_M,
    RETAINED_JUNCTION_GATE_REASON,
    SURFACE_RELEASE_AUDIT,
    SURFACE_RELEASE_PLAN_STEM,
    SURFACE_RELEASE_RISK,
    SURFACE_RELEASE_ROLLBACK_REASON,
    T05_SEMANTIC_JUNCTION_RELEASE_REASON,
    VISUAL_CONFLICT_REASON,
    VISUAL_CONFLICT_RELEASE_RISK,
    VISUAL_CONFLICT_ROLLBACK_REASON,
    VISUAL_CONFLICT_UNCONDITIONAL_ROLLBACK_FAIL_REASONS,
    _anchor_node_ids,
    _fallback_points_by_id,
    _feature_exact_ids,
    _feature_fallback_ids,
    _feature_id,
    _feature_ids,
    _ids,
    _incident_segments_by_node,
    _is_optional_junc_anchor_mapping,
    _is_original_pair_endpoint_mapping,
    _is_retained_junction_gate_plan,
    _is_t05_semantic_relation_mapping,
    _plan_mappings,
    _points_by_id,
    _preplanned_release_triggers_allowed,
    _preplanned_surface_release_plan_rows,
    _ready_segment_ids,
    _release_allowed,
    _release_plan_row,
    _release_trigger_for_mapping,
    _semantic_ids_by_node,
    _summary_input_path,
    _surface_release_plan_rows,
    _surface_status_by_node,
    _t05_relation_targets_for_step,
    _truthy_anchor,
)


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
    topology_coverage_cache: dict[Any, Any] = _ReusableCoverageCache()
    preflight_plan_rows = _preflight_replacement_plan_rows(step2_replaceable_path)
    if has_surface_inputs and preflight_plan_rows:
        with (
            preserve_read_features_cache(
                [
                    step2_replaceable_path,
                    swsd_segment_path,
                    swsd_roads_path,
                    swsd_nodes_path,
                    rcsdroad_path,
                    rcsdnode_path,
                ]
            ),
            preserve_corridor_coverage_decisions(),
            defer_replacement_plan_writes(),
        ):
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
        defer_topology_audit=has_surface_inputs,
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
    plan_rows = read_replacement_plan_rows(original_plan_path)
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
            unconditional_visual_rollback_plan_ids = _visual_conflict_unconditional_rollback_plan_ids(
                visual_added_fail_keys,
                visual_released,
                swsd_segment_path,
                incident_segments_by_node=incident_segments_by_node,
            )
            visual_rollback_plan_ids = _filter_visual_topology_rollback_plan_ids(
                visual_rollback_plan_ids,
                candidate_rows,
                unconditional_plan_ids=unconditional_visual_rollback_plan_ids,
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
    validation_temp = TemporaryDirectory(prefix=f".{resolved_run_id}_validation_")
    validation_root = Path(validation_temp.name)
    validation_run_count = 0
    latest_authoritative_transition_closure_rows: list[dict[str, Any]] = []

    def run_validation(
        plan_path: Path,
        label: str,
        *,
        decision_only: bool = False,
    ) -> tuple[T06Step3Artifacts, dict[str, Any] | None]:
        nonlocal latest_authoritative_transition_closure_rows, validation_run_count
        validation_out_root = validation_root / label
        decision_context = decision_only_validation_step3_run() if decision_only else nullcontext()
        with decision_context:
            validation_artifacts = _run_validation_step3(
                step2_replaceable_path=step2_replaceable_path,
                step2_special_junction_group_audit_path=step2_special_junction_group_audit_path,
                step2_group_replacement_audit_path=step2_group_replacement_audit_path,
                step2_replacement_plan_path=plan_path,
                swsd_segment_path=swsd_segment_path,
                swsd_roads_path=swsd_roads_path,
                swsd_nodes_path=swsd_nodes_path,
                rcsdroad_path=rcsdroad_path,
                rcsdnode_path=rcsdnode_path,
                out_root=validation_out_root,
                run_id=resolved_run_id,
                junction_surface_path=surface_inputs.get("t05_surface_path"),
                progress=progress,
                decision_only=decision_only,
            )
            validation_surface_summary = _run_surface(
                validation_artifacts,
                swsd_segment_path=swsd_segment_path,
                swsd_roads_path=swsd_roads_path,
                surface_inputs=surface_inputs,
                surface_topology_closure=surface_topology_closure,
                write_feature_json_outputs=False,
                topology_coverage_cache=topology_coverage_cache,
                validation_only=True,
            )
        validation_runtime_state = (
            validation_surface_summary.get("_step3_surface_runtime_state")
            if validation_surface_summary is not None
            else None
        )
        if (
            validation_runtime_state is not None
            and validation_runtime_state.authoritative_transition_closure_rows
        ):
            latest_authoritative_transition_closure_rows = list(
                validation_runtime_state.authoritative_transition_closure_rows
            )
        validation_run_count += 1
        return validation_artifacts, validation_surface_summary
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
    postplan_released = _postplan_anchor_release_items(candidate_rows)
    candidate_plan = _write_plan_json(step_root, candidate_rows, "candidate")
    external_baseline_root = _external_baseline_step3_root(step2_replaceable_path, step_root)
    external_baseline_fail_keys = _topology_fail_keys(external_baseline_root) if external_baseline_root else set()
    internal_baseline_fail_keys: set[tuple[str, str, str, str, str]] = set()
    internal_baseline_run_count = 0
    baseline_plan_ids = {
        str(item.get("plan_id") or "")
        for item in postplan_released
        if not item.get("independent_surface_release")
    }
    baseline_plan_ids.discard("")
    if not external_baseline_root and baseline_plan_ids:
        baseline_rows = _block_postplan_anchor_rows_for_baseline(_copy_plan_rows(candidate_rows), baseline_plan_ids)
        baseline_plan_root = validation_root / "baseline_plan" / resolved_run_id / STEP3_DIR
        baseline_plan = _write_plan_json(baseline_plan_root, baseline_rows, "postplan_baseline")
        baseline_artifacts, baseline_surface_summary = run_validation(
            baseline_plan,
            "postplan_baseline",
            decision_only=True,
        )
        internal_baseline_fail_keys = _topology_fail_keys(
            baseline_artifacts.step_root,
            _runtime_state_from_summary(baseline_surface_summary),
        )
        internal_baseline_run_count = 1
        del baseline_artifacts, baseline_surface_summary
    rollback_reference_fail_keys = external_baseline_fail_keys or internal_baseline_fail_keys
    artifacts, surface_summary = run_validation(candidate_plan, "candidate")
    current_runtime_state = _runtime_state_from_summary(surface_summary)
    full_step3_run_count = validation_run_count
    final_fail_keys = _topology_fail_keys(artifacts.step_root, current_runtime_state)
    added_fail_keys = final_fail_keys - rollback_reference_fail_keys
    postplan_added_fail_keys = _postplan_anchor_added_fail_keys(added_fail_keys)
    postplan_rollback_plan_ids: set[str] = set()
    if postplan_released:
        postplan_rollback_plan_ids = _rollback_plan_ids_for_failed_segments(
            postplan_added_fail_keys,
            postplan_released,
            incident_segments_by_node,
        )
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
        surface_safe_fail_keys = _fail_keys_after_postplan_rollback(
            surface_safe_fail_keys,
            postplan_released,
            postplan_rollback_plan_ids,
            incident_segments_by_node,
        )
        # The internal baseline only isolates the new post-plan anchor gate.
        # Existing visual-conflict releases retain their historical rollback
        # reference; otherwise the baseline would silently make unrelated
        # visual plans appear pre-approved.
        visual_reference_fail_keys = external_baseline_fail_keys if external_baseline_root else set()
        visual_added_fail_keys = surface_safe_fail_keys - visual_reference_fail_keys
        visual_non_replaced_plan_ids = _visual_conflict_non_replaced_plan_ids(
            artifacts.step_root,
            visual_released,
            relation_rows=(
                current_runtime_state.segment_relation_rows
                if current_runtime_state is not None
                else None
            ),
        )
        visual_rollback_plan_ids = _visual_conflict_rollback_plan_ids(
            visual_added_fail_keys,
            visual_released,
            swsd_segment_path,
            incident_segments_by_node=incident_segments_by_node,
        )
        unconditional_visual_rollback_plan_ids = _visual_conflict_unconditional_rollback_plan_ids(
            visual_added_fail_keys,
            visual_released,
            swsd_segment_path,
            incident_segments_by_node=incident_segments_by_node,
        )
        visual_rollback_plan_ids = _filter_visual_topology_rollback_plan_ids(
            visual_rollback_plan_ids,
            candidate_rows,
            unconditional_plan_ids=unconditional_visual_rollback_plan_ids,
        )
        visual_rollback_plan_ids.update(visual_non_replaced_plan_ids)

    topology_safe_plan: Path | None = None
    residual_postplan_rollback_plan_ids: set[str] = set()
    recommended_rollback_plan_ids = postplan_rollback_plan_ids | rollback_plan_ids | visual_rollback_plan_ids
    if recommended_rollback_plan_ids:
        safe_rows = _copy_plan_rows(candidate_rows)
        safe_rows = _rollback_postplan_anchor_release_rows(safe_rows, postplan_rollback_plan_ids)
        safe_rows = _rollback_release_rows(safe_rows, rollback_plan_ids)
        safe_rows = _rollback_visual_conflict_release_rows(safe_rows, visual_rollback_plan_ids)
        topology_safe_plan = _write_plan_json(step_root, safe_rows, "topology_safe")
        del artifacts, surface_summary, current_runtime_state
        artifacts, surface_summary = run_validation(topology_safe_plan, "topology_safe")
        current_runtime_state = _runtime_state_from_summary(surface_summary)
        full_step3_run_count = validation_run_count
        final_fail_keys = _topology_fail_keys(artifacts.step_root, current_runtime_state)
        residual_added_fail_keys = final_fail_keys - rollback_reference_fail_keys
        residual_postplan_added_fail_keys = _postplan_anchor_added_fail_keys(residual_added_fail_keys)
        if residual_postplan_added_fail_keys and postplan_released:
            residual_postplan_rollback_plan_ids = baseline_plan_ids - postplan_rollback_plan_ids
            if residual_postplan_rollback_plan_ids:
                conservative_rows = _copy_plan_rows(safe_rows)
                conservative_rows = _rollback_postplan_anchor_release_rows(
                    conservative_rows,
                    residual_postplan_rollback_plan_ids,
                )
                conservative_plan = _write_plan_json(
                    step_root,
                    conservative_rows,
                    "topology_safe_residual",
                )
                del artifacts, surface_summary, current_runtime_state
                artifacts, surface_summary = run_validation(
                    conservative_plan,
                    "topology_safe_residual",
                )
                current_runtime_state = _runtime_state_from_summary(surface_summary)
                full_step3_run_count = validation_run_count
                final_fail_keys = _topology_fail_keys(artifacts.step_root, current_runtime_state)
                retire_intermediate_step3_plan(topology_safe_plan, conservative_plan)
                topology_safe_plan = conservative_plan
                postplan_rollback_plan_ids.update(residual_postplan_rollback_plan_ids)

    hard_gate_iterations: list[dict[str, Any]] = []
    hard_gate_rollback_plan_ids: set[str] = set()
    current_plan_rows = read_replacement_plan_rows(topology_safe_plan or candidate_plan)
    for iteration in range(1, 3):
        decision = final_topology_gate_decision(
            artifacts.step_root,
            current_plan_rows,
            audit_rows=(
                current_runtime_state.topology_connectivity_audit_rows
                if current_runtime_state is not None
                else None
            ),
        )
        new_rollback_plan_ids = set(decision["rollback_plan_ids"]) - hard_gate_rollback_plan_ids
        hard_gate_iterations.append(
            {
                "iteration": iteration,
                **decision,
                "new_rollback_plan_ids": sorted(new_rollback_plan_ids),
            }
        )
        if not new_rollback_plan_ids:
            break
        hard_gate_rollback_plan_ids.update(new_rollback_plan_ids)
        failure_node_ids_by_plan_id: dict[str, set[str]] = {}
        for failure in decision["repairable_failures"]:
            node_id = str(failure.get("swsd_node_id") or "")
            if not node_id:
                continue
            for plan_id in failure.get("mapped_plan_ids") or []:
                failure_node_ids_by_plan_id.setdefault(str(plan_id), set()).add(node_id)
        hard_gate_rows = block_final_topology_gate_rows(
            current_plan_rows,
            new_rollback_plan_ids,
            failure_node_ids_by_plan_id=failure_node_ids_by_plan_id,
        )
        hard_gate_plan = _write_plan_json(
            step_root,
            hard_gate_rows,
            f"final_topology_hard_gate_{iteration}",
        )
        del artifacts, surface_summary, current_runtime_state
        artifacts, surface_summary = run_validation(
            hard_gate_plan,
            f"final_topology_hard_gate_{iteration}",
        )
        current_runtime_state = _runtime_state_from_summary(surface_summary)
        full_step3_run_count = validation_run_count
        final_fail_keys = _topology_fail_keys(artifacts.step_root, current_runtime_state)
        retire_intermediate_step3_plan(topology_safe_plan, hard_gate_plan)
        topology_safe_plan = hard_gate_plan
        current_plan_rows = hard_gate_rows

    final_runtime_state = None
    if surface_summary is not None:
        final_runtime_state = surface_summary.pop("_step3_surface_runtime_state", None)
    artifacts = promote_validation_step3_outputs(artifacts, step_root)
    final_authoritative_transition_rows = (
        final_runtime_state.authoritative_transition_closure_rows
        if final_runtime_state is not None
        else []
    )
    if not final_authoritative_transition_rows:
        final_authoritative_transition_rows = latest_authoritative_transition_closure_rows
    if final_runtime_state is None:
        raise RuntimeError("Final validation runtime state is unavailable for deferred output publication.")
    final_runtime_state.authoritative_transition_closure_rows = list(
        final_authoritative_transition_rows
    )
    materialize_deferred_replacement_plan(topology_safe_plan or candidate_plan)
    publish_deferred_validation_outputs(
        final_runtime_state,
        artifacts.step_root,
        excluded_job_names={"road", "segment_relation"},
    )
    refresh_rcsd_road_ownership_after_surface(
        step_root=artifacts.step_root,
        summary_path=artifacts.summary_path,
        swsd_segment_path=swsd_segment_path,
        frcsd_roads=(final_runtime_state.frcsd_roads if final_runtime_state is not None else None),
        swsd_segments=(final_runtime_state.swsd_segments if final_runtime_state is not None else None),
        relation_rows=(final_runtime_state.segment_relation_rows if final_runtime_state is not None else None),
        connectivity_supplement_road_ids=(
            final_runtime_state.connectivity_supplement_road_ids
            if final_runtime_state is not None
            else None
        ),
    )
    refresh_segment_construction_audit_after_surface(
        step_root=artifacts.step_root,
        summary_path=artifacts.summary_path,
        swsd_segment_path=swsd_segment_path,
        swsd_segments=(final_runtime_state.swsd_segments if final_runtime_state is not None else None),
        swsd_roads=(final_runtime_state.swsd_roads if final_runtime_state is not None else None),
        swsd_nodes=(final_runtime_state.swsd_nodes if final_runtime_state is not None else None),
        step2_replaceable_rows=(
            final_runtime_state.step2_replaceable_rows
            if final_runtime_state is not None
            else None
        ),
        relation_rows=(final_runtime_state.segment_relation_rows if final_runtime_state is not None else None),
    )
    full_step3_run_count = validation_run_count
    final_fail_keys = _topology_fail_keys(artifacts.step_root, final_runtime_state)
    final_hard_gate_decision = final_topology_gate_decision(
        artifacts.step_root,
        current_plan_rows,
        audit_rows=final_runtime_state.topology_connectivity_audit_rows,
    )
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
    final_postplan_added_fail_keys = _postplan_anchor_added_fail_keys(
        final_fail_keys - rollback_reference_fail_keys
    )
    audit = {
        "status": "preplanned_with_topology_fallback" if fallback_applied else "preplanned_without_fallback",
        "preplanned_release": True,
        "full_step3_run_count": full_step3_run_count,
        "extra_step3_run_count": max(0, full_step3_run_count - 1),
        "full_output_step3_run_count": 1,
        "validation_step3_run_count": max(0, validation_run_count - 1),
        "candidate_step3_run_count": 1,
        "fallback_step3_run_count": max(0, full_step3_run_count - 1 - internal_baseline_run_count),
        "max_fallback_step3_run_count": 4,
        "baseline_fail_count": len(rollback_reference_fail_keys) if rollback_reference_fail_keys else None,
        "internal_baseline_step3_run_count": internal_baseline_run_count,
        "candidate_added_fail_count": len(added_fail_keys),
        "final_fail_count": len(final_fail_keys),
        "final_added_fail_count": len(final_fail_keys - rollback_reference_fail_keys),
        "final_added_fail_keys": [list(item) for item in sorted(final_fail_keys - rollback_reference_fail_keys)],
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
        "postplan_anchor_gate": {
            "released_count": len(postplan_released),
            "baseline_blocked_count": len(baseline_plan_ids),
            "candidate_added_fail_count": len(postplan_added_fail_keys),
            "non_postplan_added_fail_count": len(added_fail_keys - postplan_added_fail_keys),
            "non_postplan_added_fail_keys": [
                list(item) for item in sorted(added_fail_keys - postplan_added_fail_keys)
            ],
            "final_added_fail_count": len(final_postplan_added_fail_keys),
            "final_added_fail_keys": [list(item) for item in sorted(final_postplan_added_fail_keys)],
            "rolled_back_count": len(postplan_rollback_plan_ids),
            "residual_rolled_back_count": len(residual_postplan_rollback_plan_ids),
            "released": postplan_released,
            "rolled_back_plan_ids": sorted(postplan_rollback_plan_ids),
            "residual_rolled_back_plan_ids": sorted(residual_postplan_rollback_plan_ids),
        },
        "final_topology_hard_gate": {
            "iteration_count": len(hard_gate_iterations),
            "rerun_count": sum(1 for item in hard_gate_iterations if item["new_rollback_plan_ids"]),
            "rolled_back_count": len(hard_gate_rollback_plan_ids),
            "rolled_back_plan_ids": sorted(hard_gate_rollback_plan_ids),
            "iterations": hard_gate_iterations,
            "final_decision": final_hard_gate_decision,
            "status": (
                "passed"
                if final_hard_gate_decision["repairable_failure_count"] == 0
                else "failed_unresolved_formal_topology"
            ),
        },
    }
    if visual_release_audit is not None:
        audit["visual_conflict_release"] = visual_release_audit
    _write_release_audit(artifacts.step_root, audit)
    _merge_release_summary(artifacts.summary_path, audit)
    validation_temp.cleanup()
    return artifacts, surface_summary


def _run_step3(
    *,
    write_feature_json_outputs: bool = True,
    validation_only: bool = False,
    defer_topology_audit: bool = False,
    decision_only: bool = False,
    **kwargs: Any,
) -> T06Step3Artifacts:
    topology_context = (
        defer_step3_initial_topology_audit()
        if defer_topology_audit or validation_only
        else nullcontext()
    )
    if validation_only:
        decision_context = decision_only_validation_step3_run() if decision_only else nullcontext()
        with validation_step3_run(), decision_context, defer_step3_auxiliary_audits(), topology_context, suppress_feature_json_outputs():
            return run_t06_step3_segment_replacement(**kwargs)
    if not write_feature_json_outputs:
        with defer_step3_auxiliary_audits(), topology_context, suppress_feature_json_outputs():
            return run_t06_step3_segment_replacement(**kwargs)
    with defer_step3_auxiliary_audits(), topology_context:
        return run_t06_step3_segment_replacement(**kwargs)


def _run_validation_step3(*, decision_only: bool = False, **kwargs: Any) -> T06Step3Artifacts:
    return _run_step3(
        **kwargs,
        write_feature_json_outputs=False,
        validation_only=True,
        defer_topology_audit=True,
        decision_only=decision_only,
    )


def _run_isolated_baseline(payload: dict[str, Any]) -> set[tuple[str, str, str, str, str]]:
    artifacts = _run_validation_step3(**payload["step3_kwargs"], decision_only=True)
    surface_summary = _run_surface(
        artifacts,
        **payload["surface_kwargs"],
        write_feature_json_outputs=False,
        topology_coverage_cache={},
        validation_only=True,
    )
    return _topology_fail_keys(
        artifacts.step_root,
        _runtime_state_from_summary(surface_summary),
    )


def _topology_fail_keys(
    step_root: Path,
    runtime_state: Step3SurfaceRuntimeState | None = None,
) -> set[tuple[str, str, str, str, str]]:
    return topology_fail_keys(
        step_root,
        read_rows=read_features,
        audit_rows=(
            runtime_state.topology_connectivity_audit_rows
            if runtime_state is not None
            else None
        ),
    )


def _runtime_state_from_summary(
    summary: dict[str, Any] | None,
) -> Step3SurfaceRuntimeState | None:
    state = (summary or {}).get("_step3_surface_runtime_state")
    return state if isinstance(state, Step3SurfaceRuntimeState) else None


def _run_surface(
    artifacts: T06Step3Artifacts,
    *,
    swsd_segment_path: str | Path,
    swsd_roads_path: str | Path,
    surface_inputs: dict[str, Path | None],
    surface_topology_closure: bool,
    write_feature_json_outputs: bool = True,
    topology_coverage_cache: dict[Any, Any] | None = None,
    validation_only: bool = False,
) -> dict[str, Any] | None:
    runtime_state = take_step3_surface_runtime_state(artifacts.step_root)
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
            runtime_state=runtime_state,
            defer_promotable_outputs=validation_only,
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
                runtime_state=runtime_state,
                defer_promotable_outputs=validation_only,
            )
    semantic_stats = refresh_semantic_junction_topology_audit(
        step_root=artifacts.step_root,
        summary_path=artifacts.summary_path,
        semantic_group_rows=(
            runtime_state.semantic_junction_group_rows
            if runtime_state is not None
            else None
        ),
        topology_rows=(
            runtime_state.topology_connectivity_audit_rows
            if runtime_state is not None
            else None
        ),
        write_outputs=not validation_only,
        preserve_gpkg_rewrite_semantics=validation_only,
    )
    if validation_only and runtime_state is not None:
        runtime_state.publish_topology_connectivity_json = bool(semantic_stats.get("semantic_junction_topology_fail_downgraded_count"))
    if not validation_only:
        refresh_rcsd_road_ownership_after_surface(
            step_root=artifacts.step_root,
            summary_path=artifacts.summary_path,
            swsd_segment_path=swsd_segment_path,
        )
        refresh_segment_construction_audit_after_surface(
            step_root=artifacts.step_root,
            summary_path=artifacts.summary_path,
            swsd_segment_path=swsd_segment_path,
        )
    if summary is not None:
        summary["semantic_junction_topology_refresh"] = semantic_stats
        if validation_only and runtime_state is not None:
            normalize_step3_surface_runtime_state(runtime_state)
            summary["_step3_surface_runtime_state"] = runtime_state
    return summary


def _run_surface_topology_postprocess(
    *,
    artifacts: T06Step3Artifacts,
    swsd_segment_path: str | Path,
    swsd_roads_path: str | Path,
    surface_inputs: dict[str, Path | None],
    surface_topology_closure: bool,
    topology_coverage_cache: dict[Any, Any] | None = None,
    runtime_state: Step3SurfaceRuntimeState | None = None,
    defer_promotable_outputs: bool = False,
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
        runtime_state=runtime_state,
        defer_promotable_outputs=defer_promotable_outputs,
    )

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


def _postplan_anchor_release_items(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in rows:
        props = row.get("properties") or {}
        risk_flags = set(_ids(props.get("risk_flags")))
        plan_id = str(props.get("replacement_plan_id") or "")
        if (
            not plan_id
            or props.get("plan_status") != "ready"
            or props.get("execution_action") != "replace"
            or POSTPLAN_ANCHOR_GATE_RISK not in risk_flags
        ):
            continue
        items.append(
            {
                "plan_id": plan_id,
                "segment_id": str(props.get("swsd_segment_id") or ""),
                "group_segment_ids": _ids(props.get("group_segment_ids")),
                "original_reason": str(props.get("postplan_anchor_gate_original_reason") or ""),
                "evidence": str(props.get("postplan_anchor_gate_evidence") or ""),
                "independent_surface_release": SURFACE_RELEASE_RISK in risk_flags,
            }
        )
    return items


def _block_postplan_anchor_rows_for_baseline(
    rows: list[dict[str, Any]],
    plan_ids: set[str],
) -> list[dict[str, Any]]:
    for row in rows:
        props = row.get("properties") or {}
        if str(props.get("replacement_plan_id") or "") not in plan_ids:
            continue
        props["plan_status"] = "blocked"
        props["execution_action"] = "hold"
        props["source_reason"] = props.get("postplan_anchor_gate_original_reason") or POSTPLAN_ANCHOR_GATE_RISK
        props["upstream_owner"] = "T06_step2_topology_connectivity_gate"
    return rows


def _rollback_postplan_anchor_release_rows(
    rows: list[dict[str, Any]],
    rollback_plan_ids: set[str],
) -> list[dict[str, Any]]:
    for row in rows:
        props = row.get("properties") or {}
        if str(props.get("replacement_plan_id") or "") not in rollback_plan_ids:
            continue
        props["plan_status"] = "blocked"
        props["execution_action"] = "hold"
        props["source_reason"] = POSTPLAN_ANCHOR_ROLLBACK_REASON
        props["upstream_owner"] = "T06_step3_topology_connectivity_audit"
        props["risk_flags"] = unique_preserve_order(
            [*_ids(props.get("risk_flags")), POSTPLAN_ANCHOR_ROLLBACK_REASON]
        )
        notes = str(props.get("notes") or "")
        suffix = f"blocked by {POSTPLAN_ANCHOR_ROLLBACK_REASON}"
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
    unconditional_plan_ids: set[str] | None = None,
) -> set[str]:
    unconditional_plan_ids = unconditional_plan_ids or set()
    if not rollback_plan_ids and not unconditional_plan_ids:
        return set()
    rows_by_plan_id = {
        str((row.get("properties") or {}).get("replacement_plan_id") or ""): row.get("properties") or {}
        for row in plan_rows
    }
    result: set[str] = set()
    for plan_id in rollback_plan_ids | unconditional_plan_ids:
        if plan_id in unconditional_plan_ids:
            result.add(plan_id)
            continue
        props = rows_by_plan_id.get(plan_id) or {}
        if _float_value(props.get("swsd_uncovered_by_rcsd_ratio")) > 0.0:
            result.add(plan_id)
    return result


def _visual_conflict_unconditional_rollback_plan_ids(
    added_fail_keys: set[tuple[str, str, str, str, str]],
    released: list[dict[str, Any]],
    swsd_segment_path: str | Path,
    incident_segments_by_node: dict[str, list[str]] | None = None,
) -> set[str]:
    incident = incident_segments_by_node
    if incident is None:
        incident = _incident_segments_by_node(read_features(swsd_segment_path))
    hard_fail_keys = {
        key
        for key in _visual_conflict_rollback_fail_keys(added_fail_keys)
        if (key[0], key[4]) in VISUAL_CONFLICT_UNCONDITIONAL_ROLLBACK_FAIL_REASONS
    }
    return _rollback_plan_ids_for_failed_segments(hard_fail_keys, released, incident)


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


def _visual_conflict_non_replaced_plan_ids(
    step_root: Path,
    released: list[dict[str, Any]],
    *,
    relation_rows: list[dict[str, Any]] | None = None,
) -> set[str]:
    relation_path = step_root / f"{STEP3_SWSD_FRCSD_SEGMENT_RELATION_STEM}.gpkg"
    if relation_rows is None and not relation_path.is_file():
        return set()
    status_by_segment: dict[str, str] = {}
    for row in relation_rows if relation_rows is not None else read_features(relation_path):
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
    # Visual-conflict release may only survive as a pure RCSD replacement.
    return str(status or "") == "replaced"


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


def _write_plan_json(step_root: Path, rows: list[dict[str, Any]], label: str) -> Path:
    path = step_root / f"{SURFACE_RELEASE_PLAN_STEM}_{label}.json"
    write_replacement_plan_json(path, rows)
    return path


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


def _preflight_replacement_plan_rows(step2_replaceable_path: str | Path) -> list[dict[str, Any]]:
    step2_root = Path(step2_replaceable_path).resolve().parent
    for suffix in (".json", ".geojson", ".gpkg", ".csv"):
        plan_path = step2_root / f"{STEP2_REPLACEMENT_PLAN_STEM}{suffix}"
        if plan_path.is_file():
            return read_replacement_plan_rows(plan_path)
    return []


def _external_baseline_step3_root(step2_replaceable_path: str | Path, current_step_root: Path) -> Path | None:
    step2_root = Path(step2_replaceable_path).resolve().parent
    run_root = step2_root.parent
    candidate = run_root / "step3_segment_replacement"
    if candidate.resolve() == current_step_root.resolve():
        return None
    path = candidate / f"{STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM}.gpkg"
    return candidate if path.is_file() else None
