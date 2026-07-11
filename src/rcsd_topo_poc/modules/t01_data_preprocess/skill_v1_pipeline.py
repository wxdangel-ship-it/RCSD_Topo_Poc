from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Optional, Union

from rcsd_topo_poc.modules.t01_data_preprocess import skill_v1 as _facade


def SkillV1Artifacts(*args: Any, **kwargs: Any) -> Any:
    return _facade.SkillV1Artifacts(*args, **kwargs)


def _append_jsonl(*args: Any, **kwargs: Any) -> Any:
    return _facade._append_jsonl(*args, **kwargs)


def _finalize_bundle(*args: Any, **kwargs: Any) -> Any:
    return _facade._finalize_bundle(*args, **kwargs)


def _find_repo_root(*args: Any, **kwargs: Any) -> Any:
    return _facade._find_repo_root(*args, **kwargs)


def _make_stage_subprogress_callback(*args: Any, **kwargs: Any) -> Any:
    return _facade._make_stage_subprogress_callback(*args, **kwargs)


def _now_text(*args: Any, **kwargs: Any) -> Any:
    return _facade._now_text(*args, **kwargs)


def _print_progress(*args: Any, **kwargs: Any) -> Any:
    return _facade._print_progress(*args, **kwargs)


def _resolve_oneway_continuation_context(*args: Any, **kwargs: Any) -> Any:
    return _facade._resolve_oneway_continuation_context(*args, **kwargs)


def _resolve_out_root(*args: Any, **kwargs: Any) -> Any:
    return _facade._resolve_out_root(*args, **kwargs)


def _run_stage(*args: Any, **kwargs: Any) -> Any:
    return _facade._run_stage(*args, **kwargs)


def _write_distance_gate_scope_check(*args: Any, **kwargs: Any) -> Any:
    return _facade._write_distance_gate_scope_check(*args, **kwargs)


def _write_progress_snapshot(*args: Any, **kwargs: Any) -> Any:
    return _facade._write_progress_snapshot(*args, **kwargs)


def _write_skill_terminal_outputs(*args: Any, **kwargs: Any) -> Any:
    return _facade._write_skill_terminal_outputs(*args, **kwargs)


def compare_skill_v1_bundle(*args: Any, **kwargs: Any) -> Any:
    return _facade.compare_skill_v1_bundle(*args, **kwargs)


def first_existing_vector_path(*args: Any, **kwargs: Any) -> Any:
    return _facade.first_existing_vector_path(*args, **kwargs)


def initialize_working_layers(*args: Any, **kwargs: Any) -> Any:
    return _facade.initialize_working_layers(*args, **kwargs)


def refresh_s2_baseline(*args: Any, **kwargs: Any) -> Any:
    return _facade.refresh_s2_baseline(*args, **kwargs)


def run_step2_segment_poc(*args: Any, **kwargs: Any) -> Any:
    return _facade.run_step2_segment_poc(*args, **kwargs)


def run_step4_residual_graph(*args: Any, **kwargs: Any) -> Any:
    return _facade.run_step4_residual_graph(*args, **kwargs)


def run_step5_oneway_segment_completion(*args: Any, **kwargs: Any) -> Any:
    return _facade.run_step5_oneway_segment_completion(*args, **kwargs)


def run_step5_staged_residual_graph(*args: Any, **kwargs: Any) -> Any:
    return _facade.run_step5_staged_residual_graph(*args, **kwargs)


def run_t01_skill_v1(
    *,
    road_path: Optional[Union[str, Path]] = None,
    node_path: Optional[Union[str, Path]] = None,
    continue_from_dir: Optional[Union[str, Path]] = None,
    out_root: Optional[Union[str, Path]] = None,
    run_id: Optional[str] = None,
    per_run_subdir: bool = False,
    road_layer: Optional[str] = None,
    road_crs: Optional[str] = None,
    node_layer: Optional[str] = None,
    node_crs: Optional[str] = None,
    strategy_config_path: Optional[Union[str, Path]] = None,
    formway_mode: str = "strict",
    left_turn_formway_bit: int = 8,
    debug: bool = False,
    compare_freeze_dir: Optional[Union[str, Path]] = None,
    trace_validation_pair_ids: Optional[list[str]] = None,
    stop_after_step2_validation_pair_index: Optional[int] = None,
) -> SkillV1Artifacts:
    if (
        stop_after_step2_validation_pair_index is not None
        and stop_after_step2_validation_pair_index < 1
    ):
        raise ValueError("stop_after_step2_validation_pair_index must be >= 1.")
    if continue_from_dir is not None and stop_after_step2_validation_pair_index is not None:
        raise ValueError("continue_from_dir does not support stop_after_step2_validation_pair_index.")
    if continue_from_dir is not None and trace_validation_pair_ids:
        raise ValueError("continue_from_dir does not support trace_validation_pair_ids.")
    if continue_from_dir is None and (road_path is None or node_path is None):
        raise ValueError("run_t01_skill_v1 requires road_path/node_path unless continue_from_dir is provided.")
    resolved_out_root, resolved_run_id = _resolve_out_root(
        out_root=out_root,
        run_id=run_id,
        per_run_subdir=per_run_subdir,
    )
    resolved_out_root.mkdir(parents=True, exist_ok=True)
    progress_path = resolved_out_root / "t01_skill_v1_progress.json"
    perf_json_path = resolved_out_root / "t01_skill_v1_perf.json"
    perf_md_path = resolved_out_root / "t01_skill_v1_perf.md"
    perf_markers_path = resolved_out_root / "t01_skill_v1_perf_markers.jsonl"

    if continue_from_dir is None and strategy_config_path is None:
        repo_root = _find_repo_root(resolved_out_root)
        if repo_root is None:
            raise ValueError("Cannot infer default strategy config because repo root was not found.")
        strategy_config_path = repo_root / "configs" / "t01_data_preprocess" / "step1_pair_s2.json"

    stage_timings: list[dict[str, Any]] = []
    completed_stage_names: list[str] = []
    total_started = time.perf_counter()
    total_stages = (3 if continue_from_dir is not None else 7) + (1 if compare_freeze_dir is not None else 0)
    if perf_markers_path.exists():
        perf_markers_path.unlink()

    _write_progress_snapshot(
        out_path=progress_path,
        run_id=resolved_run_id,
        status="initializing",
        total_stages=total_stages,
        completed_stage_names=completed_stage_names,
        current_stage=None,
        message="Skill v1 runner initialized.",
    )
    _append_jsonl(
        perf_markers_path,
        {
            "event": "run_start",
            "at": _now_text(),
            "run_id": resolved_run_id,
            "debug": debug,
            "total_stages": total_stages,
        },
    )
    _print_progress(f"RUN START run_id={resolved_run_id} debug={debug} total_stages={total_stages}")

    if debug:
        stage_root = resolved_out_root / "debug"
        if stage_root.exists():
            if stage_root.is_dir():
                shutil.rmtree(stage_root)
            else:
                stage_root.unlink()
        stage_root.mkdir(parents=True, exist_ok=True)
        temp_ctx = None
    else:
        temp_ctx = tempfile.TemporaryDirectory(prefix=f"{resolved_run_id}_")
        stage_root = Path(temp_ctx.name)

    try:
        if continue_from_dir is not None:
            continuation_context = _run_stage(
                name="continue_load",
                run_id=resolved_run_id,
                stage_index=1,
                total_stages=total_stages,
                stage_timings=stage_timings,
                progress_path=progress_path,
                perf_markers_path=perf_markers_path,
                completed_stage_names=completed_stage_names,
                profile_memory=debug,
                action=lambda: _resolve_oneway_continuation_context(continue_from_dir),
            )

            oneway_root = stage_root / "oneway"
            oneway_artifacts = _run_stage(
                name="oneway",
                run_id=resolved_run_id,
                stage_index=2,
                total_stages=total_stages,
                stage_timings=stage_timings,
                progress_path=progress_path,
                perf_markers_path=perf_markers_path,
                completed_stage_names=completed_stage_names,
                profile_memory=debug,
                action=lambda: run_step5_oneway_segment_completion(
                    step5_artifacts=continuation_context.step5_artifacts,
                    out_root=oneway_root,
                    run_id=resolved_run_id,
                    debug=debug,
                ),
            )

            final_nodes_path = resolved_out_root / "nodes.gpkg"
            final_roads_path = resolved_out_root / "roads.gpkg"
            bundle_info = _run_stage(
                name="step6",
                run_id=resolved_run_id,
                stage_index=3,
                total_stages=total_stages,
                stage_timings=stage_timings,
                progress_path=progress_path,
                perf_markers_path=perf_markers_path,
                completed_stage_names=completed_stage_names,
                profile_memory=debug,
                action=lambda: _finalize_continuation_bundle(
                    resolved_out_root=resolved_out_root,
                    continuation_context=continuation_context,
                    step5_artifacts=oneway_artifacts,
                    refreshed_nodes_path=oneway_artifacts.refreshed_nodes_path,
                    refreshed_roads_path=oneway_artifacts.refreshed_roads_path,
                    final_nodes_path=final_nodes_path,
                    final_roads_path=final_roads_path,
                    run_id=resolved_run_id,
                    debug=debug,
                    oneway_root=oneway_root,
                ),
            )

            distance_gate_scope_check_path = None
            if (
                continuation_context.step2_root is not None
                and continuation_context.step4_root is not None
                and continuation_context.step5_root is not None
            ):
                distance_gate_scope_check_path = _write_distance_gate_scope_check(
                    out_root=resolved_out_root,
                    step2_root=continuation_context.step2_root,
                    step4_root=continuation_context.step4_root,
                    step5_root=continuation_context.step5_root,
                )
            else:
                copied_scope_check = _copy_if_exists(
                    source_path=continuation_context.source_dir / "distance_gate_scope_check.json",
                    target_path=resolved_out_root / "distance_gate_scope_check.json",
                )
                if copied_scope_check is not None:
                    distance_gate_scope_check_path = copied_scope_check

            freeze_compare_status: Optional[str] = None
            if compare_freeze_dir is not None:
                if bundle_info.get("manifest_path") is None:
                    raise ValueError(
                        "compare_freeze_dir in continuation mode requires a previous full Skill v1 output root "
                        "or copied Skill v1 bundle exports in continue_from_dir."
                    )
                freeze_compare_status = _run_stage(
                    name="freeze_compare",
                    run_id=resolved_run_id,
                    stage_index=4,
                    total_stages=total_stages,
                    stage_timings=stage_timings,
                    progress_path=progress_path,
                    perf_markers_path=perf_markers_path,
                    completed_stage_names=completed_stage_names,
                    profile_memory=debug,
                    action=lambda: compare_skill_v1_bundle(
                        current_dir=resolved_out_root,
                        freeze_dir=compare_freeze_dir,
                        out_dir=resolved_out_root,
                    )["status"],
                )

            total_wall_time_sec = time.perf_counter() - total_started
            summary = {
                "run_id": resolved_run_id,
                "skill_version": _facade.SKILL_VERSION,
                "debug": debug,
                "continued_from_dir": str(continuation_context.source_dir.resolve()),
                "continued_from_stage_root": str(continuation_context.stage_root.resolve()),
                "input_node_path": str(continuation_context.refreshed_nodes_path.resolve()),
                "input_road_path": str(continuation_context.refreshed_roads_path.resolve()),
                "bootstrap_nodes_path": None,
                "bootstrap_roads_path": None,
                "strategy_config_path": None,
                "stages": stage_timings,
                "total_wall_time_sec": total_wall_time_sec,
                "final_nodes_path": str(final_nodes_path.resolve()),
                "final_roads_path": str(final_roads_path.resolve()),
                "bundle_manifest_path": bundle_info.get("manifest_path"),
                "bundle_summary_path": bundle_info.get("summary_path"),
                "text_bundle_path": bundle_info.get("text_bundle_path"),
                "text_bundle_size_report_path": bundle_info.get("text_bundle_size_report_path"),
                "text_bundle_size_bytes": bundle_info.get("text_bundle_size_bytes"),
                "all_stage_segment_roads_path": bundle_info.get("all_stage_segment_roads_path"),
                "segment_path": bundle_info.get("segment_path"),
                "inner_nodes_path": bundle_info.get("inner_nodes_path"),
                "segment_error_path": bundle_info.get("segment_error_path"),
                "segment_geojson_path": str(first_existing_vector_path(resolved_out_root, "segment.gpkg", "segment.geojson").resolve()) if first_existing_vector_path(resolved_out_root, "segment.gpkg", "segment.geojson") is not None else None,
                "inner_nodes_geojson_path": str(first_existing_vector_path(resolved_out_root, "inner_nodes.gpkg", "inner_nodes.geojson").resolve()) if first_existing_vector_path(resolved_out_root, "inner_nodes.gpkg", "inner_nodes.geojson") is not None else None,
                "segment_error_geojson_path": str(first_existing_vector_path(resolved_out_root, "segment_error.gpkg", "segment_error.geojson").resolve()) if first_existing_vector_path(resolved_out_root, "segment_error.gpkg", "segment_error.geojson") is not None else None,
                "step6_segment_summary_path": bundle_info.get("step6_summary_path"),
                "oneway_segment_summary_path": bundle_info.get("oneway_segment_summary_path"),
                "unsegmented_roads_path": bundle_info.get("unsegmented_roads_path"),
                "unsegmented_roads_csv_path": bundle_info.get("unsegmented_roads_csv_path"),
                "unsegmented_roads_summary_path": bundle_info.get("unsegmented_roads_summary_path"),
                "distance_gate_scope_check_path": str(distance_gate_scope_check_path.resolve()) if distance_gate_scope_check_path is not None else None,
                "freeze_compare_status": freeze_compare_status,
                "progress_path": str(progress_path.resolve()),
                "perf_json_path": str(perf_json_path.resolve()),
                "perf_md_path": str(perf_md_path.resolve()),
                "perf_markers_path": str(perf_markers_path.resolve()),
                "memory_management": {
                    "debug_default_enabled": False,
                    "stage_gc_after_run": True,
                    "bounded_parallel_load_workers": 2,
                    "uses_temp_stage_root_when_debug_false": True,
                    "deep_full_in_memory_pipeline": False,
                    "step6_reuses_step5_in_memory_records": True,
                    "step6_reuses_step5_mainnode_group_index": True,
                    "step5_alias_outputs_debug_only": True,
                    "step2_internal_progress_enabled": False,
                    "step2_retains_validation_details_in_runner": False,
                    "continuation_reuses_previous_refreshed_outputs": True,
                },
            }
            summary_path, summary_md_path = _write_skill_terminal_outputs(
                resolved_out_root=resolved_out_root,
                resolved_run_id=resolved_run_id,
                debug=debug,
                total_stages=total_stages,
                stage_timings=stage_timings,
                total_wall_time_sec=total_wall_time_sec,
                progress_path=progress_path,
                perf_json_path=perf_json_path,
                perf_md_path=perf_md_path,
                perf_markers_path=perf_markers_path,
                completed_stage_names=completed_stage_names,
                summary=summary,
                status="completed",
                message="Skill v1 continuation run completed.",
                marker_event="run_completed",
                marker_payload={"freeze_compare_status": freeze_compare_status},
            )
            _print_progress(
                f"RUN DONE run_id={resolved_run_id} total_wall={total_wall_time_sec:.3f}s "
                f"freeze_compare={freeze_compare_status or 'SKIPPED'}"
            )
            return SkillV1Artifacts(
                out_root=resolved_out_root,
                nodes_path=final_nodes_path.resolve(),
                roads_path=final_roads_path.resolve(),
                summary_path=summary_path,
                summary_md_path=summary_md_path,
                summary=summary,
            )

        bootstrap_root = stage_root / "bootstrap"
        bootstrap_artifacts = _run_stage(
            name="bootstrap",
            run_id=resolved_run_id,
            stage_index=1,
            total_stages=total_stages,
            stage_timings=stage_timings,
            progress_path=progress_path,
            perf_markers_path=perf_markers_path,
            completed_stage_names=completed_stage_names,
            profile_memory=debug,
            action=lambda: initialize_working_layers(
                road_path=road_path,
                node_path=node_path,
                out_root=bootstrap_root,
                road_layer=road_layer,
                road_crs=road_crs,
                node_layer=node_layer,
                node_crs=node_crs,
                debug=debug,
                progress_callback=_make_stage_subprogress_callback(
                    run_id=resolved_run_id,
                    stage_name="bootstrap",
                    stage_index=1,
                    total_stages=total_stages,
                    progress_path=progress_path,
                    perf_markers_path=perf_markers_path,
                    completed_stage_names=completed_stage_names,
                ),
            ),
        )

        step2_root = stage_root / "step2"
        _run_stage(
            name="step2",
            run_id=resolved_run_id,
            stage_index=2,
            total_stages=total_stages,
            stage_timings=stage_timings,
            progress_path=progress_path,
            perf_markers_path=perf_markers_path,
            completed_stage_names=completed_stage_names,
            profile_memory=debug,
            action=lambda: run_step2_segment_poc(
                road_path=bootstrap_artifacts.roads_path,
                node_path=bootstrap_artifacts.nodes_path,
                strategy_config_paths=[strategy_config_path],
                out_root=step2_root,
                run_id=resolved_run_id,
                formway_mode=formway_mode,
                left_turn_formway_bit=left_turn_formway_bit,
                debug=debug,
                retain_validation_details=False,
                assume_working_layers=True,
                trace_validation_pair_ids=trace_validation_pair_ids,
                validation_pair_index_end=stop_after_step2_validation_pair_index,
                progress_callback=_make_stage_subprogress_callback(
                    run_id=resolved_run_id,
                    stage_name="step2",
                    stage_index=2,
                    total_stages=total_stages,
                    progress_path=progress_path,
                    perf_markers_path=perf_markers_path,
                    completed_stage_names=completed_stage_names,
                ),
            ),
        )

        if stop_after_step2_validation_pair_index is not None:
            total_wall_time_sec = time.perf_counter() - total_started
            partial_step2_root = resolved_out_root / "step2_partial"
            if partial_step2_root.exists():
                shutil.rmtree(partial_step2_root)
            shutil.copytree(step2_root, partial_step2_root)
            summary = {
                "run_id": resolved_run_id,
                "skill_version": _facade.SKILL_VERSION,
                "debug": debug,
                "status": "completed_partial",
                "stopped_early": True,
                "stopped_after_stage": "step2",
                "stopped_after_step2_validation_pair_index": stop_after_step2_validation_pair_index,
                "input_node_path": str(Path(node_path).resolve()),
                "input_road_path": str(Path(road_path).resolve()),
                "bootstrap_nodes_path": str(bootstrap_artifacts.nodes_path.resolve()),
                "bootstrap_roads_path": str(bootstrap_artifacts.roads_path.resolve()),
                "strategy_config_path": str(Path(strategy_config_path).resolve()),
                "stages": stage_timings,
                "total_wall_time_sec": total_wall_time_sec,
                "partial_step2_root": str(partial_step2_root.resolve()),
                "final_nodes_path": None,
                "final_roads_path": None,
                "bundle_manifest_path": None,
                "bundle_summary_path": None,
                "text_bundle_path": None,
                "text_bundle_size_report_path": None,
                "text_bundle_size_bytes": None,
                "all_stage_segment_roads_path": None,
                "segment_path": None,
                "inner_nodes_path": None,
                "segment_error_path": None,
                "segment_geojson_path": None,
                "inner_nodes_geojson_path": None,
                "segment_error_geojson_path": None,
                "step6_segment_summary_path": None,
                "oneway_segment_summary_path": None,
                "unsegmented_roads_path": None,
                "unsegmented_roads_csv_path": None,
                "unsegmented_roads_summary_path": None,
                "distance_gate_scope_check_path": None,
                "freeze_compare_status": None,
                "progress_path": str(progress_path.resolve()),
                "perf_json_path": str(perf_json_path.resolve()),
                "perf_md_path": str(perf_md_path.resolve()),
                "perf_markers_path": str(perf_markers_path.resolve()),
                "memory_management": {
                    "debug_default_enabled": False,
                    "stage_gc_after_run": True,
                    "bounded_parallel_load_workers": 2,
                    "uses_temp_stage_root_when_debug_false": True,
                    "deep_full_in_memory_pipeline": False,
                    "step6_reuses_step5_in_memory_records": True,
                    "step6_reuses_step5_mainnode_group_index": True,
                    "step5_alias_outputs_debug_only": True,
                    "step2_internal_progress_enabled": True,
                    "step2_retains_validation_details_in_runner": False,
                },
            }
            summary_path, summary_md_path = _write_skill_terminal_outputs(
                resolved_out_root=resolved_out_root,
                resolved_run_id=resolved_run_id,
                debug=debug,
                total_stages=total_stages,
                stage_timings=stage_timings,
                total_wall_time_sec=total_wall_time_sec,
                progress_path=progress_path,
                perf_json_path=perf_json_path,
                perf_md_path=perf_md_path,
                perf_markers_path=perf_markers_path,
                completed_stage_names=completed_stage_names,
                summary=summary,
                status="completed_partial",
                message=(
                    "Skill v1 runner completed partially after Step2 validation pair "
                    f"{stop_after_step2_validation_pair_index}."
                ),
                marker_event="run_completed_partial",
                marker_payload={
                    "stopped_after_stage": "step2",
                    "stopped_after_step2_validation_pair_index": stop_after_step2_validation_pair_index,
                },
            )
            _print_progress(
                "RUN DONE PARTIAL "
                f"run_id={resolved_run_id} total_wall={total_wall_time_sec:.3f}s "
                f"stop_after_step2_validation_pair_index={stop_after_step2_validation_pair_index}"
            )
            return SkillV1Artifacts(
                out_root=resolved_out_root,
                nodes_path=Path(node_path).resolve(),
                roads_path=Path(road_path).resolve(),
                summary_path=summary_path,
                summary_md_path=summary_md_path,
                summary=summary,
            )

        refresh_root = stage_root / "refresh"
        refresh_artifacts = _run_stage(
            name="refresh",
            run_id=resolved_run_id,
            stage_index=3,
            total_stages=total_stages,
            stage_timings=stage_timings,
            progress_path=progress_path,
            perf_markers_path=perf_markers_path,
            completed_stage_names=completed_stage_names,
            profile_memory=debug,
            action=lambda: refresh_s2_baseline(
                road_path=bootstrap_artifacts.roads_path,
                node_path=bootstrap_artifacts.nodes_path,
                s2_path=step2_root,
                out_root=refresh_root,
                run_id=resolved_run_id,
                debug=debug,
                assume_working_layers=True,
            ),
        )

        step4_root = stage_root / "step4"
        step4_artifacts = _run_stage(
            name="step4",
            run_id=resolved_run_id,
            stage_index=4,
            total_stages=total_stages,
            stage_timings=stage_timings,
            progress_path=progress_path,
            perf_markers_path=perf_markers_path,
            completed_stage_names=completed_stage_names,
            profile_memory=debug,
            action=lambda: run_step4_residual_graph(
                road_path=refresh_artifacts.roads_path,
                node_path=refresh_artifacts.nodes_path,
                out_root=step4_root,
                run_id=resolved_run_id,
                formway_mode=formway_mode,
                left_turn_formway_bit=left_turn_formway_bit,
                debug=debug,
            ),
        )

        step5_root = stage_root / "step5"
        step5_artifacts = _run_stage(
            name="step5",
            run_id=resolved_run_id,
            stage_index=5,
            total_stages=total_stages,
            stage_timings=stage_timings,
            progress_path=progress_path,
            perf_markers_path=perf_markers_path,
            completed_stage_names=completed_stage_names,
            profile_memory=debug,
            action=lambda: run_step5_staged_residual_graph(
                road_path=step4_artifacts.refreshed_roads_path,
                node_path=step4_artifacts.refreshed_nodes_path,
                out_root=step5_root,
                run_id=resolved_run_id,
                formway_mode=formway_mode,
                left_turn_formway_bit=left_turn_formway_bit,
                debug=debug,
            ),
        )

        oneway_root = stage_root / "oneway"
        oneway_artifacts = _run_stage(
            name="oneway",
            run_id=resolved_run_id,
            stage_index=6,
            total_stages=total_stages,
            stage_timings=stage_timings,
            progress_path=progress_path,
            perf_markers_path=perf_markers_path,
            completed_stage_names=completed_stage_names,
            profile_memory=debug,
            action=lambda: run_step5_oneway_segment_completion(
                step5_artifacts=step5_artifacts,
                out_root=oneway_root,
                run_id=resolved_run_id,
                debug=debug,
            ),
        )

        final_nodes_path = resolved_out_root / "nodes.gpkg"
        final_roads_path = resolved_out_root / "roads.gpkg"
        bundle_info = _run_stage(
            name="step6",
            run_id=resolved_run_id,
            stage_index=7,
            total_stages=total_stages,
            stage_timings=stage_timings,
            progress_path=progress_path,
            perf_markers_path=perf_markers_path,
            completed_stage_names=completed_stage_names,
            profile_memory=debug,
            action=lambda: _finalize_bundle(
                resolved_out_root=resolved_out_root,
                step2_root=step2_root,
                step4_root=step4_root,
                step5_root=step5_root,
                step5_artifacts=oneway_artifacts,
                refreshed_nodes_path=oneway_artifacts.refreshed_nodes_path,
                refreshed_roads_path=oneway_artifacts.refreshed_roads_path,
                final_nodes_path=final_nodes_path,
                final_roads_path=final_roads_path,
                run_id=resolved_run_id,
                debug=debug,
                oneway_root=oneway_root,
                freeze_compare_nodes_path=step5_artifacts.refreshed_nodes_path,
                freeze_compare_roads_path=step5_artifacts.refreshed_roads_path,
            ),
        )
        distance_gate_scope_check_path = _write_distance_gate_scope_check(
            out_root=resolved_out_root,
            step2_root=step2_root,
            step4_root=step4_root,
            step5_root=step5_root,
        )

        freeze_compare_status: Optional[str] = None
        if compare_freeze_dir is not None:
            freeze_compare_status = _run_stage(
                name="freeze_compare",
                run_id=resolved_run_id,
                stage_index=8,
                total_stages=total_stages,
                stage_timings=stage_timings,
                progress_path=progress_path,
                perf_markers_path=perf_markers_path,
                completed_stage_names=completed_stage_names,
                profile_memory=debug,
                action=lambda: compare_skill_v1_bundle(
                    current_dir=resolved_out_root,
                    freeze_dir=compare_freeze_dir,
                    out_dir=resolved_out_root,
                )["status"],
            )

        total_wall_time_sec = time.perf_counter() - total_started
        summary = {
            "run_id": resolved_run_id,
            "skill_version": _facade.SKILL_VERSION,
            "debug": debug,
            "input_node_path": str(Path(node_path).resolve()),
            "input_road_path": str(Path(road_path).resolve()),
            "bootstrap_nodes_path": str(bootstrap_artifacts.nodes_path.resolve()),
            "bootstrap_roads_path": str(bootstrap_artifacts.roads_path.resolve()),
            "strategy_config_path": str(Path(strategy_config_path).resolve()),
            "stages": stage_timings,
            "total_wall_time_sec": total_wall_time_sec,
            "final_nodes_path": str(final_nodes_path.resolve()),
            "final_roads_path": str(final_roads_path.resolve()),
            "bundle_manifest_path": bundle_info["manifest_path"],
            "bundle_summary_path": bundle_info["summary_path"],
            "text_bundle_path": bundle_info.get("text_bundle_path"),
            "text_bundle_size_report_path": bundle_info.get("text_bundle_size_report_path"),
            "text_bundle_size_bytes": bundle_info.get("text_bundle_size_bytes"),
            "all_stage_segment_roads_path": bundle_info.get("all_stage_segment_roads_path"),
            "segment_path": bundle_info.get("segment_path"),
            "inner_nodes_path": bundle_info.get("inner_nodes_path"),
            "segment_error_path": bundle_info.get("segment_error_path"),
            "segment_geojson_path": bundle_info.get("segment_path"),
            "inner_nodes_geojson_path": bundle_info.get("inner_nodes_path"),
            "segment_error_geojson_path": bundle_info.get("segment_error_path"),
            "step6_segment_summary_path": bundle_info.get("step6_summary_path"),
            "oneway_segment_summary_path": bundle_info.get("oneway_segment_summary_path"),
            "unsegmented_roads_path": bundle_info.get("unsegmented_roads_path"),
            "unsegmented_roads_csv_path": bundle_info.get("unsegmented_roads_csv_path"),
            "unsegmented_roads_summary_path": bundle_info.get("unsegmented_roads_summary_path"),
            "distance_gate_scope_check_path": str(distance_gate_scope_check_path.resolve()),
            "freeze_compare_status": freeze_compare_status,
            "progress_path": str(progress_path.resolve()),
            "perf_json_path": str(perf_json_path.resolve()),
            "perf_md_path": str(perf_md_path.resolve()),
            "perf_markers_path": str(perf_markers_path.resolve()),
            "memory_management": {
                "debug_default_enabled": False,
                "stage_gc_after_run": True,
                "bounded_parallel_load_workers": 2,
                "uses_temp_stage_root_when_debug_false": True,
                "deep_full_in_memory_pipeline": False,
                "step6_reuses_step5_in_memory_records": True,
                "step6_reuses_step5_mainnode_group_index": True,
                "step5_alias_outputs_debug_only": True,
                "step2_internal_progress_enabled": True,
                "step2_retains_validation_details_in_runner": False,
            },
        }
        summary_path, summary_md_path = _write_skill_terminal_outputs(
            resolved_out_root=resolved_out_root,
            resolved_run_id=resolved_run_id,
            debug=debug,
            total_stages=total_stages,
            stage_timings=stage_timings,
            total_wall_time_sec=total_wall_time_sec,
            progress_path=progress_path,
            perf_json_path=perf_json_path,
            perf_md_path=perf_md_path,
            perf_markers_path=perf_markers_path,
            completed_stage_names=completed_stage_names,
            summary=summary,
            status="completed",
            message="Skill v1 runner completed.",
            marker_event="run_completed",
            marker_payload={"freeze_compare_status": freeze_compare_status},
        )
        _print_progress(
            f"RUN DONE run_id={resolved_run_id} total_wall={total_wall_time_sec:.3f}s "
            f"freeze_compare={freeze_compare_status or 'SKIPPED'}"
        )

        return SkillV1Artifacts(
            out_root=resolved_out_root,
            nodes_path=final_nodes_path,
            roads_path=final_roads_path,
            summary_path=summary_path,
            summary_md_path=summary_md_path,
            summary=summary,
        )
    finally:
        if temp_ctx is not None:
            temp_ctx.cleanup()
