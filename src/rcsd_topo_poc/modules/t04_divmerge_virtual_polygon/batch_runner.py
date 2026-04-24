from __future__ import annotations

import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    build_run_id,
    normalize_runtime_path,
    write_json,
)

from .case_loader import load_case_bundle, load_case_specs
from .event_interpretation import build_case_result
from .outputs import (
    materialize_review_gallery,
    write_case_outputs,
    write_review_index,
    write_review_summary,
    write_summary,
)
from .final_publish import write_step7_batch_outputs
from .step4_rcsd_anchored_reverse import apply_rcsd_anchored_reverse_lookup
from .step4_final_conflict_resolver import resolve_step4_final_conflicts
from .step4_road_surface_fork_binding import apply_road_surface_fork_binding


DEFAULT_CASE_ROOT = Path("/mnt/e/TestData/POC_Data/T02/Anchor_2")
DEFAULT_OUT_ROOT = Path("/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t04_step14_batch")


def _now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_preflight_doc(
    *,
    case_root: Path,
    out_root: Path,
    run_root: Path,
    case_loader_preflight: dict[str, Any],
) -> dict[str, Any]:
    return {
        "generated_at": _now_text(),
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "case_root": str(case_root),
        "out_root": str(out_root),
        "run_root": str(run_root),
        **case_loader_preflight,
    }


def run_t04_step14_batch(
    *,
    case_root: str | Path = DEFAULT_CASE_ROOT,
    case_ids: list[str] | None = None,
    max_cases: int | None = None,
    out_root: str | Path = DEFAULT_OUT_ROOT,
    run_id: str | None = None,
) -> Path:
    resolved_case_root = normalize_runtime_path(case_root)
    resolved_out_root = normalize_runtime_path(out_root)
    resolved_run_id = run_id or build_run_id("t04_step14_batch")
    run_root = resolved_out_root / resolved_run_id
    rerun_cleaned_before_write = False
    if run_root.exists():
        shutil.rmtree(run_root)
        rerun_cleaned_before_write = True
    run_root.mkdir(parents=True, exist_ok=True)

    specs, loader_preflight = load_case_specs(
        case_root=resolved_case_root,
        case_ids=case_ids,
        max_cases=max_cases,
    )
    preflight = _build_preflight_doc(
        case_root=resolved_case_root,
        out_root=resolved_out_root,
        run_root=run_root,
        case_loader_preflight=loader_preflight,
    )
    write_json(run_root / "preflight.json", preflight)

    case_results = []
    failed_case_ids: list[str] = []
    for spec in specs:
        try:
            case_bundle = load_case_bundle(spec)
            case_results.append(build_case_result(case_bundle))
        except Exception:
            failed_case_ids.append(spec.case_id)

    finalized_case_results, resolution_doc = resolve_step4_final_conflicts(case_results)
    finalized_case_results, surface_binding_doc = apply_road_surface_fork_binding(finalized_case_results)
    finalized_case_results, reverse_doc = apply_rcsd_anchored_reverse_lookup(finalized_case_results)
    write_json(run_root / "second_pass_conflict_resolution.json", resolution_doc)
    write_json(run_root / "step4_road_surface_fork_binding.json", surface_binding_doc)
    write_json(run_root / "step4_rcsd_anchored_reverse.json", reverse_doc)

    review_rows = []
    step7_artifacts = []
    for case_result in finalized_case_results:
        case_review_rows, step7_artifact = write_case_outputs(run_root=run_root, case_result=case_result)
        review_rows.extend(case_review_rows)
        step7_artifacts.append(step7_artifact)

    materialized_rows = materialize_review_gallery(run_root, review_rows)
    write_review_index(run_root, materialized_rows)
    write_review_summary(run_root, materialized_rows)
    step7_outputs = write_step7_batch_outputs(run_root=run_root, artifacts=step7_artifacts)
    write_summary(
        run_root=run_root,
        rows=materialized_rows,
        preflight=preflight,
        failed_case_ids=failed_case_ids,
        rerun_cleaned_before_write=rerun_cleaned_before_write,
        step7_outputs=step7_outputs,
    )
    return run_root


def run_t04_step14_case(
    *,
    case_dir: str | Path,
    out_root: str | Path = DEFAULT_OUT_ROOT,
    run_id: str | None = None,
) -> Path:
    resolved_case_dir = normalize_runtime_path(case_dir)
    if not resolved_case_dir.is_dir():
        raise ValueError(f"case dir does not exist: {resolved_case_dir}")
    return run_t04_step14_batch(
        case_root=resolved_case_dir.parent,
        case_ids=[resolved_case_dir.name],
        out_root=out_root,
        run_id=run_id,
    )
