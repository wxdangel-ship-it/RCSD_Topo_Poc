from __future__ import annotations

import argparse
import gc
import json
import shutil
import tempfile
import time
import tracemalloc
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar, Union

from shapely.geometry import shape

from rcsd_topo_poc.modules.t01_data_preprocess.freeze_compare import (
    compare_skill_v1_bundle,
    write_skill_v1_bundle,
)
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import (
    first_existing_vector_path,
    load_vector_feature_collection,
    write_vector,
)
from rcsd_topo_poc.modules.t01_data_preprocess.s2_baseline_refresh import refresh_s2_baseline
from rcsd_topo_poc.modules.t01_data_preprocess.step1_pair_poc import _find_repo_root
from rcsd_topo_poc.modules.t01_data_preprocess.step2_segment_poc import run_step2_segment_poc
from rcsd_topo_poc.modules.t01_data_preprocess.step4_residual_graph import run_step4_residual_graph
from rcsd_topo_poc.modules.t01_data_preprocess.step5_staged_residual_graph import run_step5_staged_residual_graph
from rcsd_topo_poc.modules.t01_data_preprocess.step6_segment_aggregation import (
    run_step6_segment_aggregation_from_records,
)
from rcsd_topo_poc.modules.t01_data_preprocess.working_layers import (
    MAX_DUAL_CARRIAGEWAY_SEPARATION_M,
    MAX_SIDE_ACCESS_DISTANCE_M,
    initialize_working_layers,
    sanitize_public_node_properties,
)


DEFAULT_RUN_ID_PREFIX = "t01_skill_v1_"
SKILL_VERSION = "1.0.0"
VALIDATION_PROGRESS_TRACE_PAIR_LIMIT = 50
VALIDATION_PROGRESS_CHECKPOINT_INTERVAL = 1000
T = TypeVar("T")


@dataclass(frozen=True)
class SkillV1Artifacts:
    out_root: Path
    nodes_path: Path
    roads_path: Path
    summary_path: Path
    summary_md_path: Path
    summary: dict[str, Any]


def _now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _print_progress(message: str) -> None:
    print(f"[{_now_text()}] {message}", flush=True)


def _write_json_doc(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _format_progress_details(payload: dict[str, Any]) -> str:
    detail_keys = (
        "strategy_id",
        "strategy_index",
        "strategy_count",
        "pair_index",
        "validation_count",
        "pair_id",
        "phase",
        "validated_status",
        "reject_reason",
        "trunk_found",
        "candidate_road_count",
        "pruned_road_count",
        "segment_road_count",
        "candidate_pair_count",
        "validated_pair_count",
        "rejected_pair_count",
        "search_seed_count",
        "terminate_count",
        "road_count",
        "physical_node_count",
        "semantic_node_count",
        "semantic_endpoint_road_count",
        "undirected_node_count",
        "output_file",
        "gc_collected_objects",
    )
    parts: list[str] = []
    for key in detail_keys:
        if key not in payload:
            continue
        parts.append(f"{key}={payload[key]}")
    return " ".join(parts)


def _should_write_subprogress_snapshot(event: str, payload: dict[str, Any]) -> bool:
    if event != "validation_pair_state":
        return True
    pair_index = payload.get("pair_index")
    validation_count = payload.get("validation_count")
    if not isinstance(pair_index, int):
        return True
    if pair_index <= VALIDATION_PROGRESS_TRACE_PAIR_LIMIT:
        return True
    if isinstance(validation_count, int) and pair_index == validation_count:
        return True
    return pair_index % VALIDATION_PROGRESS_CHECKPOINT_INTERVAL == 0


def _should_stdout_subprogress(event: str, payload: dict[str, Any], default: bool) -> bool:
    if not default:
        return False
    if event == "validation_pair_state":
        return False
    return True


def _make_stage_subprogress_callback(
    *,
    run_id: str,
    stage_name: str,
    stage_index: int,
    total_stages: int,
    progress_path: Path,
    perf_markers_path: Path,
    completed_stage_names: list[str],
) -> Callable[[str, dict[str, Any]], None]:
    def _callback(event: str, payload: dict[str, Any]) -> None:
        control_payload = dict(payload)
        perf_log = bool(control_payload.pop("_perf_log", True))
        stdout_log = _should_stdout_subprogress(
            event,
            control_payload,
            bool(control_payload.pop("_stdout_log", True)),
        )
        details = _format_progress_details(control_payload)
        message = f"Stage {stage_name} {event}."
        if details:
            message = f"{message} {details}"
        if _should_write_subprogress_snapshot(event, control_payload):
            _write_progress_snapshot(
                out_path=progress_path,
                run_id=run_id,
                status="running",
                total_stages=total_stages,
                completed_stage_names=completed_stage_names,
                current_stage=stage_name,
                message=message,
            )
        if perf_log:
            _append_jsonl(
                perf_markers_path,
                {
                    "event": "stage_subprogress",
                    "at": _now_text(),
                    "run_id": run_id,
                    "stage_index": stage_index,
                    "total_stages": total_stages,
                    "stage_name": stage_name,
                    "substage_event": event,
                    "payload": control_payload,
                },
            )
        if stdout_log:
            suffix = f" {details}" if details else ""
            _print_progress(f"[{stage_index}/{total_stages}] {stage_name}:{event}{suffix}")

    return _callback


def _write_progress_snapshot(
    *,
    out_path: Path,
    run_id: str,
    status: str,
    total_stages: int,
    completed_stage_names: list[str],
    current_stage: Optional[str] = None,
    failed_stage: Optional[str] = None,
    message: Optional[str] = None,
) -> None:
    _write_json_doc(
        out_path,
        {
            "run_id": run_id,
            "status": status,
            "updated_at": _now_text(),
            "total_stages": total_stages,
            "completed_stage_count": len(completed_stage_names),
            "completed_stage_names": completed_stage_names,
            "current_stage": current_stage,
            "failed_stage": failed_stage,
            "message": message,
        },
    )


def _build_default_run_id(now: Optional[datetime] = None) -> str:
    current = datetime.now() if now is None else now
    return f"{DEFAULT_RUN_ID_PREFIX}{current.strftime('%Y%m%d_%H%M%S')}"


def _resolve_out_root(
    *,
    out_root: Optional[Union[str, Path]],
    run_id: Optional[str],
    cwd: Optional[Path] = None,
    per_run_subdir: bool = False,
) -> tuple[Path, str]:
    resolved_run_id = run_id or _build_default_run_id()
    if out_root is not None:
        resolved_out_root = Path(out_root)
        if per_run_subdir:
            resolved_out_root = resolved_out_root / resolved_run_id
        return resolved_out_root, resolved_run_id

    repo_root = _find_repo_root(Path.cwd() if cwd is None else cwd)
    if repo_root is None:
        raise ValueError("Cannot infer default out_root because repo root was not found; please pass --out-root.")
    return repo_root / "outputs" / "_work" / "t01_skill_eval" / resolved_run_id, resolved_run_id


def _write_summary_md(*, out_path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# T01 Skill v1.0.0 Summary",
        "",
        f"- run_id: `{summary['run_id']}`",
        f"- skill_version: `{summary['skill_version']}`",
        f"- debug: `{summary['debug']}`",
        f"- total_wall_time_sec: `{summary['total_wall_time_sec']:.6f}`",
        "",
        "## Stage Timings",
        "",
    ]
    for stage in summary["stages"]:
        peak_mb = stage.get("python_tracemalloc_peak_bytes", 0) / (1024 * 1024)
        lines.append(
            f"- {stage['name']}: `{stage['wall_time_sec']:.6f}` sec; "
            f"peak_python_mem=`{peak_mb:.3f}` MiB; "
            f"gc_collected=`{stage.get('gc_collected_objects_after_stage', 0)}`"
        )
    if summary.get("freeze_compare_status"):
        lines.extend(["", "## Freeze Compare", "", f"- status: `{summary['freeze_compare_status']}`"])
    if summary.get("memory_management"):
        lines.extend(
            [
                "",
                "## Memory Management",
                "",
                f"- debug_default_enabled: `{summary['memory_management']['debug_default_enabled']}`",
                f"- stage_gc_after_run: `{summary['memory_management']['stage_gc_after_run']}`",
                f"- bounded_parallel_load_workers: `{summary['memory_management']['bounded_parallel_load_workers']}`",
                (
                    f"- uses_temp_stage_root_when_debug_false: "
                    f"`{summary['memory_management']['uses_temp_stage_root_when_debug_false']}`"
                ),
                (
                    f"- deep_full_in_memory_pipeline: "
                    f"`{summary['memory_management']['deep_full_in_memory_pipeline']}`"
                ),
            ]
        )
    if summary.get("progress_path") or summary.get("perf_json_path"):
        lines.extend(["", "## Runtime Artifacts", ""])
        if summary.get("progress_path"):
            lines.append(f"- progress_path: `{summary['progress_path']}`")
        if summary.get("perf_json_path"):
            lines.append(f"- perf_json_path: `{summary['perf_json_path']}`")
        if summary.get("perf_markers_path"):
            lines.append(f"- perf_markers_path: `{summary['perf_markers_path']}`")
        if summary.get("distance_gate_scope_check_path"):
            lines.append(f"- distance_gate_scope_check_path: `{summary['distance_gate_scope_check_path']}`")
        if summary.get("all_stage_segment_roads_path"):
            lines.append(f"- all_stage_segment_roads_path: `{summary['all_stage_segment_roads_path']}`")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _read_json_if_exists(path: Path) -> Optional[dict[str, Any]]:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _stage_gate_hook_status(summary_doc: Optional[dict[str, Any]]) -> tuple[bool, bool]:
    if not summary_doc:
        return False, False
    dual_hooked = summary_doc.get("dual_carriageway_separation_gate_limit_m") == MAX_DUAL_CARRIAGEWAY_SEPARATION_M
    side_hooked = summary_doc.get("side_access_distance_gate_limit_m") == MAX_SIDE_ACCESS_DISTANCE_M
    return bool(dual_hooked), bool(side_hooked)


def _write_distance_gate_scope_check(
    *,
    out_root: Path,
    step2_root: Path,
    step4_root: Path,
    step5_root: Path,
) -> Path:
    step2_summary = _read_json_if_exists(step2_root / "S2" / "segment_summary.json")
    step4_summary = _read_json_if_exists(step4_root / "STEP4" / "segment_summary.json")
    step5a_summary = _read_json_if_exists(step5_root / "STEP5A" / "segment_summary.json")
    step5b_summary = _read_json_if_exists(step5_root / "STEP5B" / "segment_summary.json")
    step5c_summary = _read_json_if_exists(step5_root / "STEP5C" / "segment_summary.json")

    step2_dual, step2_side = _stage_gate_hook_status(step2_summary)
    step4_dual, step4_side = _stage_gate_hook_status(step4_summary)
    step5a_dual, step5a_side = _stage_gate_hook_status(step5a_summary)
    step5b_dual, step5b_side = _stage_gate_hook_status(step5b_summary)
    step5c_dual, step5c_side = _stage_gate_hook_status(step5c_summary)

    payload = {
        "skill_version": SKILL_VERSION,
        "dual_gate_limit_m": MAX_DUAL_CARRIAGEWAY_SEPARATION_M,
        "side_gate_limit_m": MAX_SIDE_ACCESS_DISTANCE_M,
        "implementation_note": "Step4 and Step5 staged phases reuse the shared Step2 bidirectional segment kernel.",
        "step2_dual_gate_hooked": step2_dual,
        "step2_side_gate_hooked": step2_side,
        "step4_dual_gate_hooked": step4_dual,
        "step4_side_gate_hooked": step4_side,
        "step5a_dual_gate_hooked": step5a_dual,
        "step5a_side_gate_hooked": step5a_side,
        "step5b_dual_gate_hooked": step5b_dual,
        "step5b_side_gate_hooked": step5b_side,
        "step5c_present": step5c_summary is not None,
        "step5c_dual_gate_hooked": step5c_dual,
        "step5c_side_gate_hooked": step5c_side,
        "summary_paths": {
            "step2": str((step2_root / "S2" / "segment_summary.json").resolve()),
            "step4": str((step4_root / "STEP4" / "segment_summary.json").resolve()),
            "step5a": str((step5_root / "STEP5A" / "segment_summary.json").resolve()),
            "step5b": str((step5_root / "STEP5B" / "segment_summary.json").resolve()),
            "step5c": str((step5_root / "STEP5C" / "segment_summary.json").resolve()),
        },
    }
    out_path = out_root / "distance_gate_scope_check.json"
    _write_json_doc(out_path, payload)
    return out_path


def _write_all_stage_segment_roads_dir(
    *,
    out_root: Path,
    step2_root: Path,
    step4_root: Path,
    step5_root: Path,
) -> Path:
    stage_sources = [
        ("Step2", first_existing_vector_path(step2_root / "S2", "segment_body_roads.gpkg", "segment_body_roads.geojson")),
        ("Step4", first_existing_vector_path(step4_root / "STEP4", "segment_body_roads.gpkg", "segment_body_roads.geojson")),
        ("Step5A", first_existing_vector_path(step5_root / "STEP5A", "segment_body_roads.gpkg", "segment_body_roads.geojson")),
        ("Step5B", first_existing_vector_path(step5_root / "STEP5B", "segment_body_roads.gpkg", "segment_body_roads.geojson")),
        ("Step5C", first_existing_vector_path(step5_root / "STEP5C", "segment_body_roads.gpkg", "segment_body_roads.geojson")),
    ]

    out_path = out_root / "all_stage_segment_roads"
    if out_path.exists():
        if out_path.is_dir():
            shutil.rmtree(out_path)
        else:
            out_path.unlink()
    out_path.mkdir(parents=True, exist_ok=True)

    for stage_name, source_path in stage_sources:
        if source_path is None or not source_path.exists():
            continue
        shutil.copy2(source_path, out_path / f"{stage_name}_{source_path.name}")
    return out_path


def _write_perf_md(*, out_path: Path, run_id: str, debug: bool, stages: list[dict[str, Any]], total_wall_time_sec: float) -> None:
    lines = [
        "# T01 Skill v1.0.0 Perf",
        "",
        f"- run_id: `{run_id}`",
        f"- debug: `{debug}`",
        f"- total_wall_time_sec: `{total_wall_time_sec:.6f}`",
        "",
        "## Stage Checkpoints",
        "",
    ]
    for stage in stages:
        peak_mb = stage.get("python_tracemalloc_peak_bytes", 0) / (1024 * 1024)
        status = stage.get("status", "completed")
        lines.append(
            f"- {stage['name']}: status=`{status}`; "
            f"wall=`{stage.get('wall_time_sec', 0.0):.6f}` sec; "
            f"peak_python_mem=`{peak_mb:.3f}` MiB; "
            f"gc_collected=`{stage.get('gc_collected_objects_after_stage', 0)}`"
        )
        if stage.get("error_message"):
            lines.append(f"  error=`{stage['error_message']}`")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_skill_terminal_outputs(
    *,
    resolved_out_root: Path,
    resolved_run_id: str,
    debug: bool,
    total_stages: int,
    stage_timings: list[dict[str, Any]],
    total_wall_time_sec: float,
    progress_path: Path,
    perf_json_path: Path,
    perf_md_path: Path,
    perf_markers_path: Path,
    completed_stage_names: list[str],
    summary: dict[str, Any],
    status: str,
    message: str,
    marker_event: str,
    marker_payload: Optional[dict[str, Any]] = None,
) -> tuple[Path, Path]:
    summary_path = resolved_out_root / "t01_skill_v1_summary.json"
    summary_md_path = resolved_out_root / "t01_skill_v1_summary.md"
    _write_json_doc(summary_path, summary)
    _write_json_doc(
        perf_json_path,
        {
            "run_id": resolved_run_id,
            "debug": debug,
            "total_wall_time_sec": total_wall_time_sec,
            "stages": stage_timings,
            "freeze_compare_status": summary.get("freeze_compare_status"),
            "status": status,
        },
    )
    _write_summary_md(out_path=summary_md_path, summary=summary)
    _write_perf_md(
        out_path=perf_md_path,
        run_id=resolved_run_id,
        debug=debug,
        stages=stage_timings,
        total_wall_time_sec=total_wall_time_sec,
    )
    _write_progress_snapshot(
        out_path=progress_path,
        run_id=resolved_run_id,
        status=status,
        total_stages=total_stages,
        completed_stage_names=completed_stage_names,
        current_stage=None,
        message=message,
    )
    _append_jsonl(
        perf_markers_path,
        {
            "event": marker_event,
            "at": _now_text(),
            "run_id": resolved_run_id,
            "total_wall_time_sec": total_wall_time_sec,
            **(marker_payload or {}),
        },
    )
    return summary_path, summary_md_path


def _run_stage(
    *,
    name: str,
    run_id: str,
    stage_index: int,
    total_stages: int,
    stage_timings: list[dict[str, Any]],
    progress_path: Path,
    perf_markers_path: Path,
    completed_stage_names: list[str],
    action: Callable[[], T],
    profile_memory: bool = True,
) -> T:
    _print_progress(f"[{stage_index}/{total_stages}] START {name}")
    _write_progress_snapshot(
        out_path=progress_path,
        run_id=run_id,
        status="running",
        total_stages=total_stages,
        completed_stage_names=completed_stage_names,
        current_stage=name,
        message=f"Stage {name} started.",
    )
    _append_jsonl(
        perf_markers_path,
        {
            "event": "stage_start",
            "at": _now_text(),
            "run_id": run_id,
            "stage_index": stage_index,
            "total_stages": total_stages,
            "stage_name": name,
        },
    )
    if profile_memory:
        tracemalloc.start()
    started = time.perf_counter()
    try:
        result = action()
    except Exception as exc:
        wall_time = time.perf_counter() - started
        if profile_memory:
            _current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
        else:
            peak = 0
        gc_collected = gc.collect()
        stage_record = {
            "name": name,
            "status": "failed",
            "wall_time_sec": wall_time,
            "python_tracemalloc_peak_bytes": peak,
            "gc_collected_objects_after_stage": gc_collected,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        }
        stage_timings.append(stage_record)
        _append_jsonl(
            perf_markers_path,
            {
                "event": "stage_failed",
                "at": _now_text(),
                "run_id": run_id,
                "stage_index": stage_index,
                "total_stages": total_stages,
                "stage_name": name,
                "wall_time_sec": wall_time,
                "python_tracemalloc_peak_bytes": peak,
                "gc_collected_objects_after_stage": gc_collected,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        _write_progress_snapshot(
            out_path=progress_path,
            run_id=run_id,
            status="failed",
            total_stages=total_stages,
            completed_stage_names=completed_stage_names,
            current_stage=None,
            failed_stage=name,
            message=f"Stage {name} failed: {type(exc).__name__}: {exc}",
        )
        _print_progress(
            f"[{stage_index}/{total_stages}] FAIL {name} "
            f"wall={wall_time:.3f}s error={type(exc).__name__}: {exc}"
        )
        raise

    wall_time = time.perf_counter() - started
    if profile_memory:
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    else:
        peak = 0
    gc_collected = gc.collect()
    stage_record = {
        "name": name,
        "status": "completed",
        "wall_time_sec": wall_time,
        "python_tracemalloc_peak_bytes": peak,
        "gc_collected_objects_after_stage": gc_collected,
    }
    stage_timings.append(stage_record)
    completed_stage_names.append(name)
    _append_jsonl(
        perf_markers_path,
        {
            "event": "stage_completed",
            "at": _now_text(),
            "run_id": run_id,
            "stage_index": stage_index,
            "total_stages": total_stages,
            "stage_name": name,
            "wall_time_sec": wall_time,
            "python_tracemalloc_peak_bytes": peak,
            "gc_collected_objects_after_stage": gc_collected,
        },
    )
    peak_mb = peak / (1024 * 1024)
    _write_progress_snapshot(
        out_path=progress_path,
        run_id=run_id,
        status="running",
        total_stages=total_stages,
        completed_stage_names=completed_stage_names,
        current_stage=None,
        message=f"Stage {name} completed.",
    )
    _print_progress(
        f"[{stage_index}/{total_stages}] DONE {name} "
        f"wall={wall_time:.3f}s peak_python_mem={peak_mb:.3f}MiB gc={gc_collected}"
    )
    return result


def run_t01_skill_v1(
    *,
    road_path: Union[str, Path],
    node_path: Union[str, Path],
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
    debug: bool = True,
    compare_freeze_dir: Optional[Union[str, Path]] = None,
    trace_validation_pair_ids: Optional[list[str]] = None,
    stop_after_step2_validation_pair_index: Optional[int] = None,
) -> SkillV1Artifacts:
    if (
        stop_after_step2_validation_pair_index is not None
        and stop_after_step2_validation_pair_index < 1
    ):
        raise ValueError("stop_after_step2_validation_pair_index must be >= 1.")
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

    if strategy_config_path is None:
        repo_root = _find_repo_root(resolved_out_root)
        if repo_root is None:
            raise ValueError("Cannot infer default strategy config because repo root was not found.")
        strategy_config_path = repo_root / "configs" / "t01_data_preprocess" / "step1_pair_s2.json"

    stage_timings: list[dict[str, Any]] = []
    completed_stage_names: list[str] = []
    total_started = time.perf_counter()
    total_stages = 6 + (1 if compare_freeze_dir is not None else 0)
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
                "skill_version": SKILL_VERSION,
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
                "all_stage_segment_roads_path": None,
                "segment_path": None,
                "inner_nodes_path": None,
                "segment_error_path": None,
                "segment_geojson_path": None,
                "inner_nodes_geojson_path": None,
                "segment_error_geojson_path": None,
                "step6_segment_summary_path": None,
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

        final_nodes_path = resolved_out_root / "nodes.gpkg"
        final_roads_path = resolved_out_root / "roads.gpkg"
        bundle_info = _run_stage(
            name="step6",
            run_id=resolved_run_id,
            stage_index=6,
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
                step5_artifacts=step5_artifacts,
                refreshed_nodes_path=step5_artifacts.refreshed_nodes_path,
                refreshed_roads_path=step5_artifacts.refreshed_roads_path,
                final_nodes_path=final_nodes_path,
                final_roads_path=final_roads_path,
                run_id=resolved_run_id,
                debug=debug,
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
                stage_index=7,
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
            "skill_version": SKILL_VERSION,
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
            "all_stage_segment_roads_path": bundle_info.get("all_stage_segment_roads_path"),
            "segment_path": bundle_info.get("segment_path"),
            "inner_nodes_path": bundle_info.get("inner_nodes_path"),
            "segment_error_path": bundle_info.get("segment_error_path"),
            "segment_geojson_path": bundle_info.get("segment_path"),
            "inner_nodes_geojson_path": bundle_info.get("inner_nodes_path"),
            "segment_error_geojson_path": bundle_info.get("segment_error_path"),
            "step6_segment_summary_path": bundle_info.get("step6_summary_path"),
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


def _finalize_bundle(
    *,
    resolved_out_root: Path,
    step2_root: Path,
    step4_root: Path,
    step5_root: Path,
    step5_artifacts: Any,
    refreshed_nodes_path: Path,
    refreshed_roads_path: Path,
    final_nodes_path: Path,
    final_roads_path: Path,
    run_id: str,
    debug: bool,
) -> dict[str, str]:
    refreshed_nodes_doc = load_vector_feature_collection(refreshed_nodes_path)
    write_vector(
        final_nodes_path,
        (
            {
                "properties": sanitize_public_node_properties(dict(feature.get("properties") or {})),
                "geometry": shape(feature["geometry"]) if feature.get("geometry") is not None else None,
            }
            for feature in refreshed_nodes_doc.get("features", [])
        ),
    )
    shutil.copy2(refreshed_roads_path, final_roads_path)
    step6_artifacts = run_step6_segment_aggregation_from_records(
        nodes=list(step5_artifacts.step6_nodes),
        roads=list(step5_artifacts.step6_roads),
        node_properties_map=step5_artifacts.step6_node_properties_map,
        road_properties_map=step5_artifacts.step6_road_properties_map,
        mainnode_groups=step5_artifacts.step6_mainnode_groups,
        group_to_allowed_road_ids=step5_artifacts.step6_group_to_allowed_road_ids,
        node_path=final_nodes_path,
        road_path=final_roads_path,
        out_root=resolved_out_root,
        run_id=run_id,
        debug=debug,
    )
    all_stage_segment_roads_path = _write_all_stage_segment_roads_dir(
        out_root=resolved_out_root,
        step2_root=step2_root,
        step4_root=step4_root,
        step5_root=step5_root,
    )
    bundle_info = write_skill_v1_bundle(
        out_dir=resolved_out_root,
        step2_dir=step2_root / "S2",
        step4_dir=step4_root,
        step5_dir=step5_root,
        refreshed_nodes_path=final_nodes_path,
        refreshed_roads_path=final_roads_path,
        mode="current",
        skill_version=SKILL_VERSION,
    )
    bundle_info["all_stage_segment_roads_path"] = str(all_stage_segment_roads_path.resolve())
    bundle_info["segment_path"] = str(step6_artifacts.segment_path.resolve())
    bundle_info["inner_nodes_path"] = str(step6_artifacts.inner_nodes_path.resolve())
    bundle_info["segment_error_path"] = str(step6_artifacts.segment_error_path.resolve())
    bundle_info["step6_summary_path"] = str(step6_artifacts.segment_summary_path.resolve())
    return bundle_info


def run_t01_skill_v1_cli(args: argparse.Namespace) -> int:
    artifacts = run_t01_skill_v1(
        road_path=args.road_path,
        node_path=args.node_path,
        out_root=args.out_root,
        run_id=args.run_id,
        per_run_subdir=getattr(args, "per_run_subdir", False),
        road_layer=args.road_layer,
        road_crs=args.road_crs,
        node_layer=args.node_layer,
        node_crs=args.node_crs,
        strategy_config_path=args.strategy_config,
        formway_mode=args.formway_mode,
        left_turn_formway_bit=args.left_turn_formway_bit,
        debug=args.debug,
        compare_freeze_dir=args.compare_freeze_dir,
        trace_validation_pair_ids=list(getattr(args, "trace_validation_pair_ids", None) or []),
        stop_after_step2_validation_pair_index=getattr(
            args,
            "stop_after_step2_validation_pair_index",
            None,
        ),
    )
    print(json.dumps({"out_root": str(artifacts.out_root.resolve()), **artifacts.summary}, ensure_ascii=False, indent=2))
    return 0
