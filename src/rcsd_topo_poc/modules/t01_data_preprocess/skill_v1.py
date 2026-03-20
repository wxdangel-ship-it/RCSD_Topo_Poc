from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

from rcsd_topo_poc.modules.t01_data_preprocess.freeze_compare import (
    compare_skill_v1_bundle,
    write_skill_v1_bundle,
)
from rcsd_topo_poc.modules.t01_data_preprocess.s2_baseline_refresh import refresh_s2_baseline
from rcsd_topo_poc.modules.t01_data_preprocess.step1_pair_poc import _find_repo_root
from rcsd_topo_poc.modules.t01_data_preprocess.step2_segment_poc import run_step2_segment_poc
from rcsd_topo_poc.modules.t01_data_preprocess.step4_residual_graph import run_step4_residual_graph
from rcsd_topo_poc.modules.t01_data_preprocess.step5_staged_residual_graph import run_step5_staged_residual_graph


DEFAULT_RUN_ID_PREFIX = "t01_skill_v1_"
SKILL_VERSION = "1.0.0"


@dataclass(frozen=True)
class SkillV1Artifacts:
    out_root: Path
    nodes_path: Path
    roads_path: Path
    summary_path: Path
    summary_md_path: Path
    summary: dict[str, Any]


def _build_default_run_id(now: Optional[datetime] = None) -> str:
    current = datetime.now() if now is None else now
    return f"{DEFAULT_RUN_ID_PREFIX}{current.strftime('%Y%m%d_%H%M%S')}"


def _resolve_out_root(*, out_root: Optional[Union[str, Path]], run_id: Optional[str], cwd: Optional[Path] = None) -> tuple[Path, str]:
    resolved_run_id = run_id or _build_default_run_id()
    if out_root is not None:
        return Path(out_root), resolved_run_id

    repo_root = _find_repo_root(Path.cwd() if cwd is None else cwd)
    if repo_root is None:
        raise ValueError("Cannot infer default out_root because repo root was not found; please pass --out-root.")
    return repo_root / "outputs" / "_work" / "t01_skill_v1" / resolved_run_id, resolved_run_id


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
        lines.append(f"- {stage['name']}: `{stage['wall_time_sec']:.6f}` sec")
    if summary.get("freeze_compare_status"):
        lines.extend(["", "## Freeze Compare", "", f"- status: `{summary['freeze_compare_status']}`"])
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_t01_skill_v1(
    *,
    road_path: Union[str, Path],
    node_path: Union[str, Path],
    out_root: Optional[Union[str, Path]] = None,
    run_id: Optional[str] = None,
    road_layer: Optional[str] = None,
    road_crs: Optional[str] = None,
    node_layer: Optional[str] = None,
    node_crs: Optional[str] = None,
    strategy_config_path: Optional[Union[str, Path]] = None,
    formway_mode: str = "strict",
    left_turn_formway_bit: int = 8,
    debug: bool = False,
    compare_freeze_dir: Optional[Union[str, Path]] = None,
) -> SkillV1Artifacts:
    resolved_out_root, resolved_run_id = _resolve_out_root(out_root=out_root, run_id=run_id)
    resolved_out_root.mkdir(parents=True, exist_ok=True)

    if strategy_config_path is None:
        repo_root = _find_repo_root(resolved_out_root)
        if repo_root is None:
            raise ValueError("Cannot infer default strategy config because repo root was not found.")
        strategy_config_path = repo_root / "configs" / "t01_data_preprocess" / "step1_pair_s2.json"

    stage_timings: list[dict[str, Any]] = []
    total_started = time.perf_counter()

    if debug:
        stage_root = resolved_out_root / "debug"
        stage_root.mkdir(parents=True, exist_ok=True)
        temp_ctx = None
    else:
        temp_ctx = tempfile.TemporaryDirectory(prefix=f"{resolved_run_id}_")
        stage_root = Path(temp_ctx.name)

    try:
        step2_root = stage_root / "step2"
        step2_started = time.perf_counter()
        run_step2_segment_poc(
            road_path=road_path,
            node_path=node_path,
            strategy_config_paths=[strategy_config_path],
            out_root=step2_root,
            run_id=resolved_run_id,
            road_layer=road_layer,
            road_crs=road_crs,
            node_layer=node_layer,
            node_crs=node_crs,
            formway_mode=formway_mode,
            left_turn_formway_bit=left_turn_formway_bit,
            debug=debug,
        )
        stage_timings.append({"name": "step2", "wall_time_sec": time.perf_counter() - step2_started})

        refresh_root = stage_root / "refresh"
        refresh_started = time.perf_counter()
        refresh_artifacts = refresh_s2_baseline(
            road_path=road_path,
            node_path=node_path,
            s2_path=step2_root,
            out_root=refresh_root,
            run_id=resolved_run_id,
            road_layer=road_layer,
            road_crs=road_crs,
            node_layer=node_layer,
            node_crs=node_crs,
            debug=debug,
        )
        stage_timings.append({"name": "refresh", "wall_time_sec": time.perf_counter() - refresh_started})

        step4_root = stage_root / "step4"
        step4_started = time.perf_counter()
        step4_artifacts = run_step4_residual_graph(
            road_path=refresh_artifacts.roads_path,
            node_path=refresh_artifacts.nodes_path,
            out_root=step4_root,
            run_id=resolved_run_id,
            formway_mode=formway_mode,
            left_turn_formway_bit=left_turn_formway_bit,
            debug=debug,
        )
        stage_timings.append({"name": "step4", "wall_time_sec": time.perf_counter() - step4_started})

        step5_root = stage_root / "step5"
        step5_started = time.perf_counter()
        step5_artifacts = run_step5_staged_residual_graph(
            road_path=step4_artifacts.refreshed_roads_path,
            node_path=step4_artifacts.refreshed_nodes_path,
            out_root=step5_root,
            run_id=resolved_run_id,
            formway_mode=formway_mode,
            left_turn_formway_bit=left_turn_formway_bit,
            debug=debug,
        )
        stage_timings.append({"name": "step5", "wall_time_sec": time.perf_counter() - step5_started})

        final_nodes_path = resolved_out_root / "nodes.geojson"
        final_roads_path = resolved_out_root / "roads.geojson"
        shutil.copy2(step5_artifacts.refreshed_nodes_path, final_nodes_path)
        shutil.copy2(step5_artifacts.refreshed_roads_path, final_roads_path)

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

        freeze_compare_status: Optional[str] = None
        if compare_freeze_dir is not None:
            freeze_compare_status = compare_skill_v1_bundle(
                current_dir=resolved_out_root,
                freeze_dir=compare_freeze_dir,
                out_dir=resolved_out_root,
            )["status"]

        summary = {
            "run_id": resolved_run_id,
            "skill_version": SKILL_VERSION,
            "debug": debug,
            "input_node_path": str(Path(node_path).resolve()),
            "input_road_path": str(Path(road_path).resolve()),
            "strategy_config_path": str(Path(strategy_config_path).resolve()),
            "stages": stage_timings,
            "total_wall_time_sec": time.perf_counter() - total_started,
            "final_nodes_path": str(final_nodes_path.resolve()),
            "final_roads_path": str(final_roads_path.resolve()),
            "bundle_manifest_path": bundle_info["manifest_path"],
            "bundle_summary_path": bundle_info["summary_path"],
            "freeze_compare_status": freeze_compare_status,
        }
        summary_path = resolved_out_root / "t01_skill_v1_summary.json"
        summary_md_path = resolved_out_root / "t01_skill_v1_summary.md"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        _write_summary_md(out_path=summary_md_path, summary=summary)

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


def run_t01_skill_v1_cli(args: argparse.Namespace) -> int:
    artifacts = run_t01_skill_v1(
        road_path=args.road_path,
        node_path=args.node_path,
        out_root=args.out_root,
        run_id=args.run_id,
        road_layer=args.road_layer,
        road_crs=args.road_crs,
        node_layer=args.node_layer,
        node_crs=args.node_crs,
        strategy_config_path=args.strategy_config,
        formway_mode=args.formway_mode,
        left_turn_formway_bit=args.left_turn_formway_bit,
        debug=args.debug,
        compare_freeze_dir=args.compare_freeze_dir,
    )
    print(json.dumps({"out_root": str(artifacts.out_root.resolve()), **artifacts.summary}, ensure_ascii=False, indent=2))
    return 0
