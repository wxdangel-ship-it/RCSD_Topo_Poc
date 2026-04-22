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

    review_rows = []
    failed_case_ids: list[str] = []
    for spec in specs:
        try:
            case_bundle = load_case_bundle(spec)
            case_result = build_case_result(case_bundle)
            review_rows.extend(write_case_outputs(run_root=run_root, case_result=case_result))
        except Exception:
            failed_case_ids.append(spec.case_id)

    materialized_rows = materialize_review_gallery(run_root, review_rows)
    write_review_index(run_root, materialized_rows)
    write_review_summary(run_root, materialized_rows)
    write_summary(
        run_root=run_root,
        rows=materialized_rows,
        preflight=preflight,
        failed_case_ids=failed_case_ids,
        rerun_cleaned_before_write=rerun_cleaned_before_write,
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

